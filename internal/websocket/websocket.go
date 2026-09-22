// Package websocket reads and writes WebSocket frames (RFC 6455) for the
// proxy's relay (docs/ARCHITECTURE.md §8.8). It has no handshake code and
// no extensions: the relay strips Sec-WebSocket-Extensions from upgrades, so
// every frame it reads must have its reserved bits clear.
//
// A Reader returns control frames as they arrive and data messages whole,
// with fragments joined. It fails closed: anything RFC 6455 forbids (a
// reserved bit or opcode, a fragmented or oversized control frame, a
// continuation with nothing to continue, a frame masked the wrong way for
// its direction) is a protocol error, and a message larger than the
// reader's limit is ErrTooBig before its payload is read.
package websocket

import (
	"bufio"
	"crypto/rand"
	"crypto/sha1"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"sync"
	"unicode/utf8"
)

// Opcodes.
const (
	OpContinuation = 0x0
	OpText         = 0x1
	OpBinary       = 0x2
	OpClose        = 0x8
	OpPing         = 0x9
	OpPong         = 0xA
)

// Close codes the relay sends.
const (
	CloseNormal          = 1000
	CloseGoingAway       = 1001
	CloseProtocolError   = 1002
	ClosePolicyViolation = 1008
	CloseTooBig          = 1009
	CloseInternalError   = 1011
)

// MaxControl is the longest payload a control frame may carry.
const MaxControl = 125

// ErrTooBig is returned for a message longer than the reader's limit.
var ErrTooBig = errors.New("websocket: message too big")

// ProtocolError is a frame RFC 6455 does not allow.
type ProtocolError string

func (e ProtocolError) Error() string { return "websocket: " + string(e) }

// Message is a control frame or a whole data message.
type Message struct {
	Op   byte // OpText, OpBinary, OpClose, OpPing or OpPong
	Data []byte
}

// IsControl reports whether m is a control frame.
func (m Message) IsControl() bool { return m.Op >= OpClose }

// Reader reads one direction of a connection.
type Reader struct {
	r          *bufio.Reader
	fromClient bool // frames must be masked (sent by a client) or must not be (by a server)
	max        int

	partOp byte // the opcode of the message being assembled, 0 when none
	part   []byte
}

// NewReader returns a reader of frames sent by a client (masked) or by a
// server (unmasked), whose data messages may be at most max bytes.
func NewReader(r *bufio.Reader, fromClient bool, max int) *Reader {
	return &Reader{r: r, fromClient: fromClient, max: max}
}

// Next returns the next control frame or complete data message.
func (r *Reader) Next() (Message, error) {
	for {
		fin, op, payload, err := r.frame()
		if err != nil {
			return Message{}, err
		}
		switch {
		case op >= OpClose:
			return Message{Op: op, Data: payload}, nil
		case op == OpContinuation:
			if r.partOp == 0 {
				return Message{}, ProtocolError("continuation frame with no message to continue")
			}
			r.part = append(r.part, payload...)
		default:
			if r.partOp != 0 {
				return Message{}, ProtocolError("new message before the last one finished")
			}
			r.partOp, r.part = op, payload
		}
		if fin {
			m := Message{Op: r.partOp, Data: r.part}
			r.partOp, r.part = 0, nil
			return m, nil
		}
	}
}

// frame reads one frame and returns its payload, unmasked.
func (r *Reader) frame() (fin bool, op byte, payload []byte, err error) {
	var h [2]byte
	if _, err := io.ReadFull(r.r, h[:]); err != nil {
		return false, 0, nil, err
	}
	fin, op = h[0]&0x80 != 0, h[0]&0x0F
	if h[0]&0x70 != 0 {
		return false, 0, nil, ProtocolError("reserved bits set, and no extension was negotiated")
	}
	switch op {
	case OpContinuation, OpText, OpBinary:
	case OpClose, OpPing, OpPong:
		if !fin {
			return false, 0, nil, ProtocolError("fragmented control frame")
		}
	default:
		return false, 0, nil, ProtocolError(fmt.Sprintf("reserved opcode %#x", op))
	}
	masked := h[1]&0x80 != 0
	if masked != r.fromClient {
		if r.fromClient {
			return false, 0, nil, ProtocolError("unmasked frame from a client")
		}
		return false, 0, nil, ProtocolError("masked frame from a server")
	}
	n := uint64(h[1] & 0x7F)
	switch n {
	case 126:
		var b [2]byte
		if _, err := io.ReadFull(r.r, b[:]); err != nil {
			return false, 0, nil, unexpected(err)
		}
		n = uint64(binary.BigEndian.Uint16(b[:]))
	case 127:
		var b [8]byte
		if _, err := io.ReadFull(r.r, b[:]); err != nil {
			return false, 0, nil, unexpected(err)
		}
		n = binary.BigEndian.Uint64(b[:])
		if n>>63 != 0 {
			return false, 0, nil, ProtocolError("frame length with its high bit set")
		}
	}
	if op >= OpClose {
		if n > MaxControl {
			return false, 0, nil, ProtocolError("control frame longer than 125 bytes")
		}
	} else if n > uint64(r.max) || uint64(len(r.part))+n > uint64(r.max) {
		return false, 0, nil, ErrTooBig
	}
	var key [4]byte
	if masked {
		if _, err := io.ReadFull(r.r, key[:]); err != nil {
			return false, 0, nil, unexpected(err)
		}
	}
	payload = make([]byte, n)
	if _, err := io.ReadFull(r.r, payload); err != nil {
		return false, 0, nil, unexpected(err)
	}
	if masked {
		maskBytes(key, payload)
	}
	if op == OpClose && len(payload) == 1 {
		return false, 0, nil, ProtocolError("close frame with a one-byte payload")
	}
	return fin, op, payload, nil
}

func unexpected(err error) error {
	if err == io.EOF {
		return io.ErrUnexpectedEOF
	}
	return err
}

func maskBytes(key [4]byte, b []byte) {
	for i := range b {
		b[i] ^= key[i&3]
	}
}

// Writer writes frames in one direction, one frame per message. Writes are
// serialised, so several goroutines may share one.
type Writer struct {
	mu   sync.Mutex
	w    io.Writer
	mask bool // frames to a server are masked
}

// NewWriter returns a writer of frames to a server (masked) or to a client
// (unmasked).
func NewWriter(w io.Writer, toServer bool) *Writer {
	return &Writer{w: w, mask: toServer}
}

// Write sends m as one final frame.
func (w *Writer) Write(m Message) error {
	if m.IsControl() && len(m.Data) > MaxControl {
		return ProtocolError("control frame longer than 125 bytes")
	}
	n := len(m.Data)
	head := make([]byte, 0, 14+n)
	head = append(head, 0x80|m.Op)
	maskBit := byte(0)
	if w.mask {
		maskBit = 0x80
	}
	switch {
	case n < 126:
		head = append(head, maskBit|byte(n))
	case n <= 0xFFFF:
		head = append(head, maskBit|126, byte(n>>8), byte(n))
	default:
		head = append(head, maskBit|127)
		head = binary.BigEndian.AppendUint64(head, uint64(n))
	}
	frame := head
	if w.mask {
		var key [4]byte
		if _, err := rand.Read(key[:]); err != nil {
			return err
		}
		frame = append(frame, key[:]...)
		start := len(frame)
		frame = append(frame, m.Data...)
		maskBytes(key, frame[start:])
	} else {
		frame = append(frame, m.Data...)
	}
	w.mu.Lock()
	defer w.mu.Unlock()
	_, err := w.w.Write(frame)
	if f, ok := w.w.(interface{ Flush() error }); ok && err == nil {
		err = f.Flush()
	}
	return err
}

// CloseMessage is a close frame with code and reason, the reason cut to
// fit a control frame without splitting a character.
func CloseMessage(code int, reason string) Message {
	max := MaxControl - 2
	if len(reason) > max {
		reason = reason[:max]
		for len(reason) > 0 && !utf8.ValidString(reason) {
			reason = reason[:len(reason)-1]
		}
	}
	data := binary.BigEndian.AppendUint16(nil, uint16(code))
	return Message{Op: OpClose, Data: append(data, reason...)}
}

// acceptGUID is the key suffix RFC 6455 §1.3 fixes.
const acceptGUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

// AcceptKey is the Sec-WebSocket-Accept value for a Sec-WebSocket-Key.
func AcceptKey(key string) string {
	h := sha1.Sum([]byte(key + acceptGUID))
	return base64.StdEncoding.EncodeToString(h[:])
}
