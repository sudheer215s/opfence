package websocket

import (
	"bufio"
	"bytes"
	"encoding/binary"
	"errors"
	"io"
	"strings"
	"testing"
)

// frame builds one frame by hand, masked with key when key is not nil.
func frame(fin bool, rsv, op byte, key []byte, payload []byte) []byte {
	b0 := op | rsv<<4
	if fin {
		b0 |= 0x80
	}
	out := []byte{b0}
	mask := byte(0)
	if key != nil {
		mask = 0x80
	}
	switch n := len(payload); {
	case n < 126:
		out = append(out, mask|byte(n))
	case n <= 0xFFFF:
		out = append(out, mask|126, byte(n>>8), byte(n))
	default:
		out = append(out, mask|127)
		out = binary.BigEndian.AppendUint64(out, uint64(n))
	}
	p := append([]byte(nil), payload...)
	if key != nil {
		out = append(out, key...)
		for i := range p {
			p[i] ^= key[i%4]
		}
	}
	return append(out, p...)
}

var key = []byte{1, 2, 3, 4}

func reader(data []byte, fromClient bool) *Reader {
	return NewReader(bufio.NewReader(bytes.NewReader(data)), fromClient, 1<<10)
}

func TestReaderAssemblesMessages(t *testing.T) {
	var in []byte
	in = append(in, frame(false, 0, OpText, key, []byte("hel"))...)
	in = append(in, frame(true, 0, OpPing, key, []byte("p"))...) // between fragments
	in = append(in, frame(false, 0, OpContinuation, key, []byte("lo "))...)
	in = append(in, frame(true, 0, OpContinuation, key, []byte("world"))...)
	in = append(in, frame(true, 0, OpBinary, key, bytes.Repeat([]byte{7}, 300))...)
	in = append(in, frame(true, 0, OpClose, key, []byte{0x03, 0xe8, 'b', 'y', 'e'})...)
	r := reader(in, true)
	want := []Message{
		{OpPing, []byte("p")},
		{OpText, []byte("hello world")},
		{OpBinary, bytes.Repeat([]byte{7}, 300)},
		{OpClose, []byte{0x03, 0xe8, 'b', 'y', 'e'}},
	}
	for i, w := range want {
		m, err := r.Next()
		if err != nil || m.Op != w.Op || !bytes.Equal(m.Data, w.Data) {
			t.Fatalf("message %d: %v %q, %v; want %v %q", i, m.Op, m.Data, err, w.Op, w.Data)
		}
	}
	if _, err := r.Next(); err != io.EOF {
		t.Fatalf("after the last frame: %v", err)
	}
}

func TestReaderFailsClosed(t *testing.T) {
	big := bytes.Repeat([]byte{1}, 1<<10)
	for name, c := range map[string]struct {
		in         []byte
		fromClient bool
		want       string
	}{
		"reserved bit":            {frame(true, 4, OpText, key, []byte("x")), true, "reserved bits"},
		"reserved opcode":         {frame(true, 0, 0x3, key, nil), true, "reserved opcode"},
		"reserved control opcode": {frame(true, 0, 0xB, key, nil), true, "reserved opcode"},
		"fragmented ping":         {frame(false, 0, OpPing, key, nil), true, "fragmented control"},
		"long ping":               {frame(true, 0, OpPing, key, bytes.Repeat([]byte{1}, 126)), true, "longer than 125"},
		"lone continuation":       {frame(true, 0, OpContinuation, key, []byte("x")), true, "no message to continue"},
		"unmasked from a client":  {frame(true, 0, OpText, nil, []byte("x")), true, "unmasked"},
		"masked from a server":    {frame(true, 0, OpText, key, []byte("x")), false, "masked frame from a server"},
		"one-byte close":          {frame(true, 0, OpClose, key, []byte{3}), true, "one-byte"},
		"interleaved message": {append(frame(false, 0, OpText, key, []byte("a")), frame(true, 0, OpText, key, []byte("b"))...),
			true, "before the last one finished"},
		"too big":           {frame(true, 0, OpBinary, key, append(big, 1)), true, "too big"},
		"too big in pieces": {append(frame(false, 0, OpBinary, key, big), frame(true, 0, OpContinuation, key, []byte{1})...), true, "too big"},
		"high length bit":   {append([]byte{0x82, 0x80 | 127, 0x80, 0, 0, 0, 0, 0, 0, 1}, key...), true, "high bit"},
		"truncated payload": {frame(true, 0, OpText, key, []byte("hello"))[:8], true, "unexpected EOF"},
	} {
		t.Run(name, func(t *testing.T) {
			r := reader(c.in, c.fromClient)
			var err error
			for err == nil {
				_, err = r.Next()
			}
			if !strings.Contains(err.Error(), c.want) {
				t.Fatalf("got %v, want %q", err, c.want)
			}
			if c.want == "too big" && !errors.Is(err, ErrTooBig) {
				t.Fatalf("got %v, want ErrTooBig", err)
			}
		})
	}
}

// A message is refused before its payload is read, so a huge length costs
// nothing.
func TestReaderRefusesHugeLengthUpFront(t *testing.T) {
	in := append([]byte{0x82, 0x80 | 127, 0, 0, 0, 1, 0, 0, 0, 0}, key...)
	if _, err := reader(in, true).Next(); !errors.Is(err, ErrTooBig) {
		t.Fatal(err)
	}
}

func TestWriterRoundTrip(t *testing.T) {
	for _, toServer := range []bool{true, false} {
		var buf bytes.Buffer
		w := NewWriter(&buf, toServer)
		msgs := []Message{
			{OpText, []byte("hi")},
			{OpBinary, bytes.Repeat([]byte{9}, 200)},
			{OpBinary, bytes.Repeat([]byte{8}, 70000)},
			{OpPing, nil},
			CloseMessage(ClosePolicyViolation, "Blocked by Opfence"),
		}
		for _, m := range msgs {
			orig := append([]byte(nil), m.Data...)
			if err := w.Write(m); err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(orig, m.Data) {
				t.Fatal("Write changed the caller's data")
			}
		}
		r := NewReader(bufio.NewReader(&buf), toServer, 1<<20)
		for i, want := range msgs {
			m, err := r.Next()
			if err != nil || m.Op != want.Op || !bytes.Equal(m.Data, want.Data) {
				t.Fatalf("toServer=%v message %d: %v %v", toServer, i, m.Op, err)
			}
		}
	}
	if err := NewWriter(io.Discard, false).Write(Message{Op: OpPing, Data: make([]byte, 126)}); err == nil {
		t.Fatal("a long ping was written")
	}
}

func TestCloseMessageFits(t *testing.T) {
	m := CloseMessage(ClosePolicyViolation, strings.Repeat("é", 100))
	if len(m.Data) > MaxControl || binary.BigEndian.Uint16(m.Data) != ClosePolicyViolation {
		t.Fatalf("%d bytes", len(m.Data))
	}
	if r := string(m.Data[2:]); !strings.HasPrefix(r, "éé") || !utf8Valid(r) {
		t.Fatalf("reason %q", r)
	}
}

func utf8Valid(s string) bool { return strings.ToValidUTF8(s, "�") == s }

func TestAcceptKey(t *testing.T) {
	// RFC 6455 §1.3.
	if got := AcceptKey("dGhlIHNhbXBsZSBub25jZQ=="); got != "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" {
		t.Fatal(got)
	}
}

func FuzzReader(f *testing.F) {
	f.Add(frame(true, 0, OpText, key, []byte("hello")), true)
	f.Add(append(frame(false, 0, OpBinary, nil, []byte("a")), frame(true, 0, OpContinuation, nil, []byte("b"))...), false)
	f.Add(frame(true, 0, OpClose, key, []byte{3, 232}), true)
	f.Fuzz(func(t *testing.T, data []byte, fromClient bool) {
		r := NewReader(bufio.NewReader(bytes.NewReader(data)), fromClient, 4096)
		for i := 0; i < 100; i++ {
			m, err := r.Next()
			if err != nil {
				return
			}
			if m.IsControl() && len(m.Data) > MaxControl || !m.IsControl() && len(m.Data) > 4096 {
				t.Fatalf("message of %d bytes", len(m.Data))
			}
			// What the relay writes back reads the same.
			var buf bytes.Buffer
			if err := NewWriter(&buf, fromClient).Write(m); err != nil {
				t.Fatal(err)
			}
			again, err := NewReader(bufio.NewReader(&buf), fromClient, 4096).Next()
			if err != nil || again.Op != m.Op || !bytes.Equal(again.Data, m.Data) {
				t.Fatalf("round trip: %v %v", again, err)
			}
		}
	})
}
