package proxy

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"testing"

	"github.com/rakeshnitb23/opfence/internal/decode"
	"github.com/rakeshnitb23/opfence/internal/secrets"
	"github.com/rakeshnitb23/opfence/internal/websocket"
)

// echoAPI accepts any upgrade, records the upgrade's URL and headers and
// every message, and answers each text message with reply(message).
type echoAPI struct {
	mu       sync.Mutex
	urls     []string
	upgrades []http.Header
	got      []string
	reply    func(string) string
	sub      string // the subprotocol it picks, if any
}

func (a *echoAPI) respond(w http.ResponseWriter, r *http.Request) {
	if !decode.IsWebSocketUpgrade(r.Method, r.Header) {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	c, brw, err := w.(http.Hijacker).Hijack()
	if err != nil {
		return
	}
	defer c.Close()
	a.mu.Lock()
	a.urls = append(a.urls, r.URL.RequestURI())
	a.upgrades = append(a.upgrades, r.Header.Clone())
	a.mu.Unlock()
	fmt.Fprintf(c, "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n", websocket.AcceptKey(r.Header.Get("Sec-WebSocket-Key")))
	if a.sub != "" {
		fmt.Fprintf(c, "Sec-WebSocket-Protocol: %s\r\n", a.sub)
	}
	fmt.Fprint(c, "\r\n")
	rd, wr := websocket.NewReader(brw.Reader, true, 1<<20), websocket.NewWriter(c, false)
	for {
		m, err := rd.Next()
		if err != nil || m.Op == websocket.OpClose {
			return
		}
		a.mu.Lock()
		a.got = append(a.got, string(m.Data))
		a.mu.Unlock()
		if m.Op == websocket.OpText && a.reply != nil {
			if out := a.reply(string(m.Data)); out != "" {
				_ = wr.Write(websocket.Message{Op: websocket.OpText, Data: []byte(out)})
			}
		}
	}
}

func (a *echoAPI) messages() []string {
	a.mu.Lock()
	defer a.mu.Unlock()
	return append([]string(nil), a.got...)
}

func secretSet(t *testing.T, provider, value string) (*secrets.Set, string) {
	t.Helper()
	ph, err := secrets.NewPlaceholder(value, nil)
	if err != nil {
		t.Fatal(err)
	}
	return secrets.NewSet([]*secrets.Secret{{Provider: provider, Name: "key", Value: value, Placeholder: ph}}), ph
}

// Supabase Realtime through the relay: the key in the upgrade's query and
// the join's token are swapped in, a join is forwarded, and a broadcast
// nobody approves gets an error reply while the channel stays open.
func TestWebSocketRealtime(t *testing.T) {
	real := "eyJhbGciOiJIUzI1NiJ9." + strings.Repeat("c2VydmljZQ", 6) + ".sig"
	set, ph := secretSet(t, "supabase-project", real)
	api := &echoAPI{reply: func(m string) string {
		var arr []json.RawMessage
		if json.Unmarshal([]byte(m), &arr) != nil || len(arr) != 5 {
			return ""
		}
		return fmt.Sprintf(`[%s,%s,%s,"phx_reply",{"status":"ok","response":{}}]`, arr[0], arr[1], arr[2])
	}}
	e := newEnv(t, opts{secrets: set, respond: api.respond})
	c := e.dialWSProtocol("abcdefghijklmnopqrst.supabase.co", "/realtime/v1/websocket?apikey="+ph+"&vsn=2.0.0", "")
	if c.resp.StatusCode != http.StatusSwitchingProtocols {
		t.Fatalf("upgrade %d", c.resp.StatusCode)
	}
	c.send(`["1","1","realtime:room-1","phx_join",{"config":{"broadcast":{"self":false}},"access_token":"` + ph + `"}]`)
	if m := c.next(); !strings.Contains(string(m.Data), `"phx_reply",{"status":"ok"`) {
		t.Fatalf("join reply %s", m.Data)
	}
	c.send(`["1","2","realtime:room-1","broadcast",{"type":"broadcast","event":"wipe","payload":{}}]`)
	if m := c.next(); !strings.Contains(string(m.Data), `"2","realtime:room-1","phx_reply",{"response":{"reason":"Blocked by Opfence: Send realtime message wipe on realtime:room-1`) {
		t.Fatalf("broadcast reply %s", m.Data)
	}
	c.send(`[null,"3","phoenix","heartbeat",{}]`)
	if m := c.next(); !strings.Contains(string(m.Data), `"3","phoenix","phx_reply"`) {
		t.Fatalf("after the block: %s", m.Data)
	}
	api.mu.Lock()
	url := api.urls[0]
	api.mu.Unlock()
	if !strings.Contains(url, "apikey="+real) || strings.Contains(url, ph) {
		t.Fatalf("upgrade went to %s", url)
	}
	got := api.messages()
	if len(got) != 2 || !strings.Contains(got[0], `"access_token":"`+real+`"`) || strings.Contains(got[1], "wipe") {
		t.Fatalf("the API got %q", got)
	}
}

// Hrana over the relay: the hello's token is swapped in, only a JSON
// subprotocol is offered, SQL stored on the connection is decided when it
// runs, and a blocked request gets response_error while the stream goes on.
func TestWebSocketHrana(t *testing.T) {
	real := "eyJ0dXJzbyI6MX0." + strings.Repeat("dG9rZW4", 6) + ".sig"
	set, ph := secretSet(t, "turso", real)
	api := &echoAPI{sub: "hrana3", reply: func(m string) string {
		var msg struct {
			Type      string
			RequestID json.RawMessage `json:"request_id"`
		}
		_ = json.Unmarshal([]byte(m), &msg)
		if msg.Type == "hello" {
			return `{"type":"hello_ok"}`
		}
		return fmt.Sprintf(`{"type":"response_ok","request_id":%s,"response":{"type":"execute","result":{"cols":[],"rows":[["%s"]]}}}`, msg.RequestID, real)
	}}
	e := newEnv(t, opts{secrets: set, respond: api.respond})
	c := e.dialWSProtocol("app-db-acme.aws-us-east-1.turso.io", "/", "hrana3-protobuf, hrana3, hrana2")
	if c.resp.StatusCode != http.StatusSwitchingProtocols || c.resp.Header.Get("Sec-WebSocket-Protocol") != "hrana3" {
		t.Fatalf("upgrade %d %v", c.resp.StatusCode, c.resp.Header)
	}
	api.mu.Lock()
	offered := api.upgrades[0].Get("Sec-WebSocket-Protocol")
	api.mu.Unlock()
	if offered != "hrana3, hrana2" {
		t.Fatalf("offered %q", offered)
	}
	c.send(`{"type":"hello","jwt":"` + ph + `"}`)
	if m := c.next(); string(m.Data) != `{"type":"hello_ok"}` {
		t.Fatalf("hello %s", m.Data)
	}
	c.send(`{"type":"request","request_id":1,"request":{"type":"execute","stream_id":0,"stmt":{"sql":"SELECT token FROM keys"}}}`)
	if m := c.next(); !strings.Contains(string(m.Data), ph) || strings.Contains(string(m.Data), real) {
		t.Fatalf("read %s", m.Data)
	}
	c.send(`{"type":"request","request_id":2,"request":{"type":"store_sql","sql_id":3,"sql":"DROP TABLE users"}}`)
	c.next()
	c.send(`{"type":"request","request_id":4,"request":{"type":"execute","stream_id":0,"stmt":{"sql_id":3}}}`)
	if m := c.next(); !strings.Contains(string(m.Data), `"request_id":4,"type":"response_error"`) || !strings.Contains(string(m.Data), "DROP TABLE users") {
		t.Fatalf("blocked %s", m.Data)
	}
	c.send(`{"type":"request","request_id":5,"request":{"type":"close_stream","stream_id":0}}`)
	if m := c.next(); !strings.Contains(string(m.Data), `"request_id":5`) {
		t.Fatalf("after the block: %s", m.Data)
	}
	got := api.messages()
	if len(got) != 4 || !strings.Contains(got[0], real) || strings.Contains(got[0], ph) {
		t.Fatalf("the API got %q", got)
	}
	for _, m := range got {
		if strings.Contains(m, `"request_id":4`) {
			t.Fatalf("the blocked request reached the API: %s", m)
		}
	}
}

// A client that offers only subprotocols Opfence does not read is refused.
func TestWebSocketUnreadableSubprotocol(t *testing.T) {
	api := &echoAPI{}
	e := newEnv(t, opts{respond: api.respond})
	c := e.dialWSProtocol("app-db-acme.aws-us-east-1.turso.io", "/", "hrana3-protobuf")
	if c.resp.StatusCode != http.StatusForbidden || e.hits.Load() != 0 {
		t.Fatalf("%d, %d hits", c.resp.StatusCode, e.hits.Load())
	}
}
