package proxy

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"testing"

	"github.com/rakeshnitb23/opfence/internal/decode"
	"github.com/rakeshnitb23/opfence/internal/secrets"
	"github.com/rakeshnitb23/opfence/internal/websocket"
)

const neonEndpoint = "ep-cool-darkness-123456.us-east-2.aws.neon.tech"

func pgMessage(t byte, body []byte) []byte {
	return append(binary.BigEndian.AppendUint32([]byte{t}, uint32(4+len(body))), body...)
}

func pgStartupMessage(user, db string) []byte {
	params := []byte("user\x00" + user + "\x00database\x00" + db + "\x00\x00")
	out := binary.BigEndian.AppendUint32(nil, uint32(8+len(params)))
	out = binary.BigEndian.AppendUint32(out, 3<<16)
	return append(out, params...)
}

func pgQueryMessage(sql string) []byte { return pgMessage('Q', append([]byte(sql), 0)) }

// neonAPI is a fake Neon WebSocket proxy: it reads the Postgres stream and
// answers every query with one row holding leak, split across two socket
// messages, as a TCP stream relayed in pieces would be.
type neonAPI struct {
	mu      sync.Mutex
	queries []string
	closed  bool
	leak    string
}

func (a *neonAPI) respond(w http.ResponseWriter, r *http.Request) {
	if !decode.IsWebSocketUpgrade(r.Method, r.Header) || r.URL.Path != "/v2" {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	c, brw, err := w.(http.Hijacker).Hijack()
	if err != nil {
		return
	}
	defer c.Close()
	fmt.Fprintf(c, "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n", websocket.AcceptKey(r.Header.Get("Sec-WebSocket-Key")))
	rd, wr := websocket.NewReader(brw.Reader, true, 1<<20), websocket.NewWriter(c, false)
	send := func(b []byte) { _ = wr.Write(websocket.Message{Op: websocket.OpBinary, Data: b}) }
	ready := pgMessage('Z', []byte{'I'})
	var stream []byte
	started := false
	for {
		m, err := rd.Next()
		if err != nil || m.Op == websocket.OpClose {
			a.mu.Lock()
			a.closed = true
			a.mu.Unlock()
			return
		}
		stream = append(stream, m.Data...)
		for {
			if !started {
				if len(stream) < 4 || len(stream) < int(binary.BigEndian.Uint32(stream)) {
					break
				}
				stream, started = stream[binary.BigEndian.Uint32(stream):], true
				send(append(pgMessage('R', []byte{0, 0, 0, 0}), ready...))
				continue
			}
			if len(stream) < 5 || len(stream) < 1+int(binary.BigEndian.Uint32(stream[1:5])) {
				break
			}
			n := 1 + int(binary.BigEndian.Uint32(stream[1:5]))
			typ, body := stream[0], stream[5:n]
			stream = stream[n:]
			if typ != 'Q' {
				continue
			}
			a.mu.Lock()
			a.queries = append(a.queries, string(bytes.TrimSuffix(body, []byte{0})))
			a.mu.Unlock()
			val := []byte(a.leak)
			row := pgMessage('D', append(binary.BigEndian.AppendUint32([]byte{0, 1}, uint32(len(val))), val...))
			half := 10 + len(val)/2 // inside the value
			send(row[:half])
			send(append(append(row[half:], pgMessage('C', []byte("SELECT 1\x00"))...), ready...))
		}
	}
}

// readPG reads socket messages until want bytes of the Postgres stream
// have arrived.
func (c *wsClient) readPG(want int) []byte {
	c.t.Helper()
	var got []byte
	for len(got) < want {
		m := c.next()
		if m.Op == websocket.OpClose {
			c.t.Fatalf("closed after %q", got)
		}
		got = append(got, m.Data...)
	}
	return got
}

// The stage 28b exit criterion: through Neon's WebSocket transport a SELECT
// returns its rows, with a secret in them scrubbed even when the row came
// in two pieces, and a DROP TABLE is blocked before it leaves the machine.
func TestWebSocketPostgres(t *testing.T) {
	real := "sk_live_" + strings.Repeat("Ab9", 10)
	placeholder, err := secrets.NewPlaceholder(real, []string{"sk_live_"})
	if err != nil {
		t.Fatal(err)
	}
	set := secrets.NewSet([]*secrets.Secret{{Provider: "stripe", Name: "key", Value: real, Placeholder: placeholder}})
	api := &neonAPI{leak: real}
	e := newEnv(t, opts{secrets: set, respond: api.respond})
	c := e.dialWSProtocol(neonEndpoint, "/v2", "")
	if c.resp.StatusCode != http.StatusSwitchingProtocols {
		t.Fatalf("upgrade %d", c.resp.StatusCode)
	}
	send := func(b []byte) {
		if err := c.w.Write(websocket.Message{Op: websocket.OpBinary, Data: b}); err != nil {
			t.Fatal(err)
		}
	}
	send(append(pgStartupMessage("neondb_owner", "neondb"), pgMessage('p', []byte("npg_EXAMPLE\x00"))...))
	if got := c.readPG(15); got[0] != 'R' || got[9] != 'Z' {
		t.Fatalf("auth: %q", got)
	}
	send(pgQueryMessage("SELECT secret FROM keys"))
	rowLen := 1 + 4 + 2 + 4 + len(real)
	got := c.readPG(rowLen + 14 + 6)
	if !bytes.Contains(got, []byte(placeholder)) || bytes.Contains(got, []byte(real)) {
		t.Fatalf("row: %q", got)
	}

	send(pgQueryMessage("DROP TABLE users"))
	m := c.next()
	if m.Op != websocket.OpBinary || m.Data[0] != 'E' || !bytes.Contains(m.Data, []byte("C42501\x00")) ||
		!bytes.Contains(m.Data, []byte("Blocked by Opfence: Run SQL on database neondb at Neon endpoint "+neonEndpoint+": DROP TABLE users")) {
		t.Fatalf("blocked: %q", m.Data)
	}
	if m := c.next(); m.Op != websocket.OpClose || binary.BigEndian.Uint16(m.Data) != websocket.ClosePolicyViolation {
		t.Fatalf("close: %v %q", m.Op, m.Data)
	}
	api.mu.Lock()
	defer api.mu.Unlock()
	if len(api.queries) != 1 || api.queries[0] != "SELECT secret FROM keys" {
		t.Fatalf("the API got %q", api.queries)
	}
	var blocked bool
	for _, en := range e.entries() {
		if en.Event == "message" && en.Outcome == "blocked" && en.Operations[0].Rule == "neon-sql.socket.query" && en.Operations[0].Class == "irreversible" {
			blocked = true
		}
		if strings.Contains(fmt.Sprint(en), "npg_EXAMPLE") {
			t.Fatalf("the password reached the audit log: %+v", en)
		}
	}
	if !blocked {
		t.Fatalf("no blocked entry: %+v", e.entries())
	}
}
