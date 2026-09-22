package decode

import (
	"encoding/binary"
	"fmt"
	"strings"
	"sync"

	"github.com/rakeshnitb23/opfence/internal/request"
)

// WSPostgres is the Postgres frontend/backend protocol carried in binary
// WebSocket messages as a byte stream, as Neon's serverless driver speaks it
// (Pool and Client): the socket is the TLS, so the protocol inside is plain.
const WSPostgres = "postgres"

// Postgres message names rules can match.
const (
	PGQuery  = "query"  // a simple Query or an extended-protocol Parse; args sql
	PGCancel = "cancel" // a CancelRequest, the first and only message of its connection
)

// maxPGMessage bounds one Postgres message the session reassembles.
const maxPGMessage = 16 << 20

// Startup codes (PostgreSQL protocol, "Message Formats").
const (
	pgProtocol3   = 3 << 16
	pgSSLRequest  = 80877103
	pgGSSENC      = 80877104
	pgCancel      = 80877102
	pgMaxStartup  = 10000 // what the server itself accepts
	pgErrorPolicy = "42501"
)

// pgWS reads the Postgres protocol inside a socket (docs/ARCHITECTURE.md
// §3.5). Frontend messages are read as a stream, across socket messages;
// every Query and Parse is an operation whose SQL is classified as
// Postgres. The startup message's user and database, with the socket's
// host, are the connection argument, like the HTTP driver's
// Neon-Connection-String. Anything it cannot read is an operation with
// Error set; when one is let through, nothing after it is read.
type pgWS struct {
	path string
	conn map[string]any // connection: host, user, database

	started bool   // the startup message has been read
	raw     bool   // something unreadable went through: pass the rest
	buf     []byte // client bytes not yet a whole message

	mu     sync.Mutex // guards the server side, which another goroutine reads
	srv    []byte
	srvRaw bool // the server side is no longer read (TLS inside, or a huge message)
	srvSSL bool // the server answers an SSLRequest with one byte next
}

func newPGWS(handshake *request.Request) *pgWS {
	return &pgWS{path: handshake.Path, conn: map[string]any{"host": handshake.Host}}
}

// pgStep is what the stream asks for after one socket message.
type pgStep struct {
	ops      []Operation
	forward  []byte
	rawAfter bool // the rest of the stream cannot be read
	ssl      bool // an SSLRequest goes to the server
}

func (p *pgWS) Client(m WSMessage) WSStep {
	if p.raw {
		return WSStep{Kind: "data", Forward: []WSMessage{m}}
	}
	if !m.Binary {
		s := wsFailed(p.path, "message", "a text message where Postgres sends binary ones", m)
		s.Forward[0].Binary = false
		return s
	}
	p.buf = append(p.buf, m.Data...)
	var st pgStep
	for !st.rawAfter {
		n, more := p.next(&st)
		if !more {
			break
		}
		st.forward = append(st.forward, p.buf[:n]...)
		p.buf = p.buf[n:]
	}
	if st.rawAfter {
		// What follows cannot be read; it goes as it is if allowed.
		st.forward = append(st.forward, p.buf...)
		p.buf = nil
	}
	kind := "data"
	for _, op := range st.ops {
		kind = op.Method
		if op.Method == PGQuery {
			break
		}
	}
	step := WSStep{Kind: kind, Ops: st.ops, Body: st.forward, raw: st.rawAfter, ssl: st.ssl}
	if len(st.forward) > 0 {
		step.Forward = []WSMessage{{Binary: true, Data: st.forward}}
	}
	return step
}

// next reads one message at the start of p.buf, adding any operation it
// is to st, and returns its length, or false when the buffer does not hold
// a whole message yet (or st became unreadable).
func (p *pgWS) next(st *pgStep) (int, bool) {
	fail := func(msg string) (int, bool) {
		st.ops = append(st.ops, p.op("message", nil, msg))
		st.rawAfter = true
		return 0, false
	}
	if !p.started {
		if len(p.buf) < 8 {
			return 0, false
		}
		n := int(binary.BigEndian.Uint32(p.buf))
		if n < 8 || n > pgMaxStartup {
			return fail(fmt.Sprintf("a Postgres startup message of %d bytes", n))
		}
		if len(p.buf) < n {
			return 0, false
		}
		switch code := binary.BigEndian.Uint32(p.buf[4:8]); {
		case code == pgSSLRequest || code == pgGSSENC:
			st.ops = append(st.ops, p.op("tls", nil, "Postgres asked for TLS inside the socket, which Opfence cannot read"))
			st.rawAfter, st.ssl = true, true
			return n, true
		case code == pgCancel:
			st.ops = append(st.ops, p.op(PGCancel, nil, ""))
			p.started = true
			return n, true
		case code>>16 == 3:
			params, ok := cstrings(p.buf[8:n])
			if !ok || len(params)%2 != 0 {
				return fail("a Postgres startup message Opfence cannot read")
			}
			for i := 0; i < len(params); i += 2 {
				switch params[i] {
				case "user", "database":
					p.conn[params[i]] = params[i+1]
				}
			}
			if _, ok := p.conn["database"]; !ok && p.conn["user"] != nil {
				p.conn["database"] = p.conn["user"] // the server's default
			}
			p.started = true
			return n, true
		default:
			return fail(fmt.Sprintf("a Postgres startup message with code %d", code))
		}
	}
	if len(p.buf) < 5 {
		return 0, false
	}
	l := int(binary.BigEndian.Uint32(p.buf[1:5]))
	if l < 4 || l > maxPGMessage {
		return fail(fmt.Sprintf("a Postgres message of %d bytes", l))
	}
	n := 1 + l
	if len(p.buf) < n {
		return 0, false
	}
	body := p.buf[5:n]
	switch typ := p.buf[0]; typ {
	case 'Q':
		sql, ok := cstring(body)
		st.ops = append(st.ops, p.query(sql, ok && len(sql)+1 == len(body), ""))
	case 'P':
		// Parse: statement name, query, parameter types.
		name, ok1 := cstring(body)
		sql, ok2 := "", false
		if ok1 {
			sql, ok2 = cstring(body[len(name)+1:])
		}
		st.ops = append(st.ops, p.query(sql, ok1 && ok2, name))
	case 'F':
		// A function called by its OID, outside any SQL.
		st.ops = append(st.ops, p.op("function_call", nil, ""))
	case 'B', 'E', 'D', 'S', 'H', 'C', 'X', 'd', 'c', 'f', 'p':
		// Bind, Execute, Describe, Sync, Flush, Close, Terminate, the copy
		// messages and authentication: they run only what Parse or Query
		// brought, which was decided then.
	default:
		return fail(fmt.Sprintf("a Postgres message Opfence does not know (%q)", typ))
	}
	return n, true
}

// query is a Query or Parse operation.
func (p *pgWS) query(sql string, ok bool, prepared string) Operation {
	switch {
	case !ok:
		return p.op(PGQuery, nil, "a Postgres query message Opfence cannot read")
	case len(sql) > request.MaxBody:
		return p.op(PGQuery, nil, "SQL larger than 64 KiB")
	}
	args := map[string]any{"sql": sql}
	if prepared != "" {
		args["prepared"] = prepared
	}
	return p.op(PGQuery, args, "")
}

func (p *pgWS) op(method string, args map[string]any, err string) Operation {
	if args == nil {
		args = map[string]any{}
	}
	conn := make(map[string]any, len(p.conn))
	for k, v := range p.conn {
		conn[k] = v
	}
	args["connection"] = conn
	return Operation{Protocol: WebSocket, Method: method, Path: p.path, Args: args, Error: err}
}

func (p *pgWS) Forwarded(s WSStep) {
	if s.raw {
		p.raw = true
	}
	if s.ssl {
		p.mu.Lock()
		p.srvSSL = true
		p.mu.Unlock()
	}
}

// Server reassembles the server's messages, so each reaches the scrubber
// whole; one larger than maxPGMessage, and everything after TLS starts,
// passes as it comes.
func (p *pgWS) Server(m WSMessage) []WSMessage {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.srvRaw || !m.Binary {
		return []WSMessage{m}
	}
	p.srv = append(p.srv, m.Data...)
	var out []byte
	for len(p.srv) > 0 {
		if p.srvSSL {
			// The one-byte answer: S starts TLS, N carries on in the clear.
			p.srvSSL = false
			if p.srv[0] == 'S' {
				p.srvRaw = true
				out = append(out, p.srv...)
				p.srv = nil
				break
			}
			out = append(out, p.srv[0])
			p.srv = p.srv[1:]
			continue
		}
		if len(p.srv) < 5 {
			break
		}
		l := int(binary.BigEndian.Uint32(p.srv[1:5]))
		if l < 4 || l > maxPGMessage {
			p.srvRaw = true
			out = append(out, p.srv...)
			p.srv = nil
			break
		}
		if len(p.srv) < 1+l {
			break
		}
		out = append(out, p.srv[:1+l]...)
		p.srv = p.srv[1+l:]
	}
	if p.srv != nil {
		p.srv = append([]byte(nil), p.srv...) // do not pin the message
	}
	if len(out) == 0 {
		return nil
	}
	return []WSMessage{{Binary: true, Data: out}}
}

// Blocked answers with an ErrorResponse and closes the socket: messages
// after the blocked one may depend on it (a Bind, a transaction's COMMIT),
// and closing rolls back a transaction it was part of.
func (p *pgWS) Blocked(s WSStep, reason string) ([]WSMessage, bool) {
	return []WSMessage{{Binary: true, Data: PGErrorResponse(pgErrorPolicy, reason)}}, true
}

// PGErrorResponse is a Postgres ErrorResponse message with SQLSTATE code
// and message msg.
func PGErrorResponse(code, msg string) []byte {
	msg = strings.ReplaceAll(msg, "\x00", "")
	var fields []byte
	for _, f := range [][2]string{{"S", "ERROR"}, {"V", "ERROR"}, {"C", code}, {"M", msg}} {
		fields = append(fields, f[0][0])
		fields = append(fields, f[1]...)
		fields = append(fields, 0)
	}
	fields = append(fields, 0)
	out := []byte{'E'}
	out = binary.BigEndian.AppendUint32(out, uint32(4+len(fields)))
	return append(out, fields...)
}

// cstring reads a NUL-terminated string from the start of b.
func cstring(b []byte) (string, bool) {
	for i, c := range b {
		if c == 0 {
			return string(b[:i]), true
		}
	}
	return "", false
}

// cstrings reads NUL-terminated strings up to the empty one that ends a
// startup message's parameters.
func cstrings(b []byte) ([]string, bool) {
	var out []string
	for len(b) > 0 {
		s, ok := cstring(b)
		if !ok {
			return nil, false
		}
		if s == "" {
			return out, len(b) == 1
		}
		out = append(out, s)
		b = b[len(s)+1:]
	}
	return nil, false
}
