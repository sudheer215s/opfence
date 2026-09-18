package decode

import (
	"bytes"
	"encoding/binary"
	"strings"
	"testing"

	"github.com/rakeshnitb23/opfence/internal/request"
)

func pgMsg(t byte, body []byte) []byte {
	return append(binary.BigEndian.AppendUint32([]byte{t}, uint32(4+len(body))), body...)
}

func pgStartup(params ...string) []byte {
	var b []byte
	for _, p := range params {
		b = append(append(b, p...), 0)
	}
	b = append(b, 0)
	out := binary.BigEndian.AppendUint32(nil, uint32(8+len(b)))
	out = binary.BigEndian.AppendUint32(out, 3<<16)
	return append(out, b...)
}

func pgQuery(sql string) []byte { return pgMsg('Q', append([]byte(sql), 0)) }

func pgParse(name, sql string) []byte {
	return pgMsg('P', append(append(append([]byte(name), 0), sql...), 0, 0, 0))
}

func pgSession() *pgWS {
	h := upgrade("/v2")
	h.Host = "ep-1.us-east-2.aws.neon.tech"
	return NewWSSession(WSPostgres, "", h, Hints{}).(*pgWS)
}

func bin(parts ...[]byte) WSMessage { return WSMessage{Binary: true, Data: bytes.Join(parts, nil)} }

func TestPostgresSession(t *testing.T) {
	s := pgSession()
	// Startup and password, pipelined: nothing to decide, all forwarded.
	start := bin(pgStartup("user", "app", "database", "orders"), pgMsg('p', []byte("secret\x00")))
	st := s.Client(start)
	if st.Decides() || len(st.Forward) != 1 || !bytes.Equal(st.Forward[0].Data, start.Data) {
		t.Fatalf("startup: %+v", st)
	}
	s.Forwarded(st)
	// A query split across socket messages is decided once it is whole.
	q := pgQuery("DROP TABLE users")
	if st := s.Client(bin(q[:7])); st.Decides() || len(st.Forward) != 0 {
		t.Fatalf("half a query: %+v", st)
	}
	st = s.Client(bin(q[7:], pgParse("s1", "SELECT 1"), pgMsg('S', nil)))
	if len(st.Ops) != 2 || st.Kind != PGQuery || !bytes.Equal(st.Forward[0].Data, append(q, append(pgParse("s1", "SELECT 1"), pgMsg('S', nil)...)...)) {
		t.Fatalf("query: %+v", st)
	}
	conn := map[string]any{"host": "ep-1.us-east-2.aws.neon.tech", "user": "app", "database": "orders"}
	for i, want := range []string{"DROP TABLE users", "SELECT 1"} {
		op := st.Ops[i]
		if op.Protocol != WebSocket || op.Method != PGQuery || op.Path != "/v2" || op.Args["sql"] != want || op.Error != "" {
			t.Fatalf("op %d: %+v", i, op)
		}
		c := op.Args["connection"].(map[string]any)
		if len(c) != 3 || c["host"] != conn["host"] || c["user"] != "app" || c["database"] != "orders" {
			t.Fatalf("connection %v", c)
		}
	}
	if st.Ops[1].Args["prepared"] != "s1" {
		t.Fatalf("%v", st.Ops[1].Args)
	}
	// The password never becomes an argument.
	for _, op := range st.Ops {
		for k := range op.Args {
			if strings.Contains(k, "pass") {
				t.Fatalf("%v", op.Args)
			}
		}
	}
	// Bind, Execute and the rest pass.
	if st := s.Client(bin(pgMsg('B', make([]byte, 8)), pgMsg('E', make([]byte, 5)), pgMsg('X', nil))); st.Decides() || len(st.Forward) != 1 {
		t.Fatalf("bind: %+v", st)
	}
	// The database defaults to the user.
	s2 := pgSession()
	s2.Client(bin(pgStartup("user", "neondb_owner")))
	if op := s2.Client(bin(pgQuery("SELECT 1"))).Ops[0]; op.Args["connection"].(map[string]any)["database"] != "neondb_owner" {
		t.Fatalf("%v", op.Args)
	}
}

func TestPostgresSessionFailsClosed(t *testing.T) {
	started := func() *pgWS {
		s := pgSession()
		s.Forwarded(s.Client(bin(pgStartup("user", "u"))))
		return s
	}
	for name, c := range map[string]struct {
		s    *pgWS
		msg  WSMessage
		kind string
	}{
		"function call":     {started(), bin(pgMsg('F', make([]byte, 10))), "function_call"},
		"unknown type":      {started(), bin(pgMsg('Z', nil)), "message"},
		"bad length":        {started(), bin([]byte{'Q', 0, 0, 0, 2}), "message"},
		"huge length":       {started(), bin([]byte{'Q', 0x7f, 0, 0, 0}), "message"},
		"unterminated sql":  {started(), bin(pgMsg('Q', []byte("DROP TABLE x"))), PGQuery},
		"sql after the nul": {started(), bin(pgMsg('Q', []byte("SELECT 1\x00; DROP TABLE x\x00"))), PGQuery},
		"big sql":           {started(), bin(pgQuery("SELECT '" + strings.Repeat("a", request.MaxBody) + "'")), PGQuery},
		"text message":      {started(), WSMessage{Data: pgQuery("SELECT 1")}, "message"},
		"startup code":      {pgSession(), bin(binary.BigEndian.AppendUint32(binary.BigEndian.AppendUint32(nil, 8), 1234)), "message"},
		"startup too long":  {pgSession(), bin(binary.BigEndian.AppendUint32(nil, 20000), make([]byte, 4)), "message"},
		"startup params":    {pgSession(), bin(pgStartup("user")), "message"},
	} {
		st := c.s.Client(c.msg)
		if len(st.Ops) == 0 {
			t.Errorf("%s: nothing to decide", name)
			continue
		}
		op := st.Ops[len(st.Ops)-1]
		if op.Method != c.kind || (op.Error == "" && c.kind != "function_call") {
			t.Errorf("%s: %+v", name, op)
		}
		if replies, closeSocket := c.s.Blocked(st, "Blocked by Opfence: no."); !closeSocket || len(replies) != 1 || replies[0].Data[0] != 'E' {
			t.Errorf("%s: blocked %v %v", name, replies, closeSocket)
		}
	}
	// An unreadable stream that is let through is not read any further.
	s := started()
	st := s.Client(bin(pgMsg('Z', nil), pgQuery("DROP TABLE x")))
	if len(st.Ops) != 1 || !bytes.Contains(st.Forward[0].Data, []byte("DROP TABLE x")) {
		t.Fatalf("%+v", st)
	}
	s.Forwarded(st)
	if st := s.Client(bin(pgQuery("DROP TABLE y"))); st.Decides() || len(st.Forward) != 1 {
		t.Fatalf("after: %+v", st)
	}
}

// TLS inside the socket is unknown; once it is let through, neither side
// is read, and the server's one-byte answer is handled.
func TestPostgresSessionTLS(t *testing.T) {
	s := pgSession()
	ssl := binary.BigEndian.AppendUint32(binary.BigEndian.AppendUint32(nil, 8), pgSSLRequest)
	st := s.Client(bin(ssl, []byte{0x16, 3, 1}))
	if len(st.Ops) != 1 || st.Ops[0].Method != "tls" || st.Ops[0].Error == "" || len(st.Forward[0].Data) != 11 {
		t.Fatalf("%+v", st)
	}
	s.Forwarded(st)
	if out := s.Server(bin([]byte{'S', 0x16, 3, 3})); len(out) != 1 || len(out[0].Data) != 4 {
		t.Fatalf("server %v", out)
	}
	if out := s.Server(bin([]byte{0x17, 3, 3, 0, 1})); len(out) != 1 || len(out[0].Data) != 5 {
		t.Fatalf("server after TLS %v", out)
	}
	if st := s.Client(bin([]byte{0x17, 3, 3})); st.Decides() {
		t.Fatalf("%+v", st)
	}
	// N: the server carries on in the clear, and its messages are read.
	s = pgSession()
	s.Forwarded(s.Client(bin(ssl)))
	if out := s.Server(bin([]byte{'N'}, pgMsg('R', make([]byte, 4))[:3])); len(out) != 1 || !bytes.Equal(out[0].Data, []byte{'N'}) {
		t.Fatalf("N: %v", out)
	}
}

// The server's messages are reassembled so each is scrubbed whole.
func TestPostgresSessionServer(t *testing.T) {
	s := pgSession()
	row := pgMsg('D', append([]byte{0, 1, 0, 0, 0, 20}, "sk_live_0123456789ab"...))
	ready := pgMsg('Z', []byte{'I'})
	if out := s.Server(bin(row[:12])); out != nil {
		t.Fatalf("half a row: %v", out)
	}
	out := s.Server(bin(row[12:], ready[:2]))
	if len(out) != 1 || !bytes.Equal(out[0].Data, row) {
		t.Fatalf("row: %v", out)
	}
	if out := s.Server(bin(ready[2:])); len(out) != 1 || !bytes.Equal(out[0].Data, ready) {
		t.Fatalf("ready: %v", out)
	}
	// A message too large to hold passes as it comes.
	huge := []byte{'D', 0x7f, 0, 0, 0, 1, 2}
	if out := s.Server(bin(huge)); len(out) != 1 || !bytes.Equal(out[0].Data, huge) {
		t.Fatalf("huge: %v", out)
	}
}

func TestPostgresCancel(t *testing.T) {
	s := pgSession()
	c := binary.BigEndian.AppendUint32(binary.BigEndian.AppendUint32(nil, 16), pgCancel)
	c = binary.BigEndian.AppendUint32(binary.BigEndian.AppendUint32(c, 1), 2)
	if st := s.Client(bin(c)); len(st.Ops) != 1 || st.Ops[0].Method != PGCancel || st.Ops[0].Error != "" {
		t.Fatalf("%+v", st)
	}
}

func TestPGErrorResponse(t *testing.T) {
	b := PGErrorResponse("42501", "Blocked by Opfence: x\x00y")
	if b[0] != 'E' || int(binary.BigEndian.Uint32(b[1:5])) != len(b)-1 || !bytes.Contains(b, []byte("C42501\x00")) ||
		!bytes.Contains(b, []byte("MBlocked by Opfence: xy\x00")) || b[len(b)-1] != 0 {
		t.Fatalf("%q", b)
	}
}

// A header on the upgrade cannot rename the database a socket's messages
// reach, as Neon-Connection-String names it for HTTP.
func TestWebSocketIgnoresHeaderArgs(t *testing.T) {
	h := upgrade("/v2")
	h.Host = "ep-prod.us-east-2.aws.neon.tech"
	h.Header.Set("Neon-Connection-String", "postgres://u@ep-dev.us-east-2.aws.neon.tech/db")
	hints := Hints{WebSocket: []WebSocketPath{{Path: "/v2", Protocol: WSPostgres}}, HeaderArgs: []HeaderArg{{Header: "Neon-Connection-String", Arg: "connection", Parse: "url"}}}
	op := Decode(h, hints)[0]
	if op.Args["connection"].(map[string]any)["host"] != "ep-prod.us-east-2.aws.neon.tech" {
		t.Fatalf("connect %v", op.Args)
	}
	s := NewWSSession(WSPostgres, "", h, hints)
	s.Client(bin(pgStartup("user", "u")))
	ops := ApplyHints(s.Client(bin(pgQuery("DROP TABLE x"))).Ops, h, hints)
	if ops[0].Args["connection"].(map[string]any)["host"] != "ep-prod.us-east-2.aws.neon.tech" {
		t.Fatalf("message %v", ops[0].Args)
	}
}

func FuzzPostgresSession(f *testing.F) {
	f.Add(pgStartup("user", "u", "database", "d"), pgQuery("SELECT 1"), 3)
	f.Add(pgStartup("user", "u"), append(pgParse("", "DELETE FROM t"), pgMsg('S', nil)...), 1)
	f.Fuzz(func(t *testing.T, a, b []byte, split int) {
		s := pgSession()
		data := append(append([]byte(nil), a...), b...)
		if split < 0 || split > len(data) {
			split = len(data) / 2
		}
		var forwarded []byte
		for _, part := range [][]byte{data[:split], data[split:]} {
			st := s.Client(WSMessage{Binary: true, Data: part})
			for _, op := range st.Ops {
				if op.Protocol != WebSocket || op.Args["connection"] == nil {
					t.Fatalf("%+v", op)
				}
			}
			for _, m := range st.Forward {
				forwarded = append(forwarded, m.Data...)
			}
			s.Forwarded(st)
			s.Server(WSMessage{Binary: true, Data: part})
		}
		// Bytes are forwarded in order and never invented.
		if !bytes.HasPrefix(data, forwarded) {
			t.Fatalf("forwarded %q of %q", forwarded, data)
		}
	})
}
