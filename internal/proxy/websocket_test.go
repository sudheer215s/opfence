package proxy

import (
	"bufio"
	"crypto/tls"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/rakeshnitb23/opfence/internal/decode"
	"github.com/rakeshnitb23/opfence/internal/secrets"
	"github.com/rakeshnitb23/opfence/internal/websocket"
)

// wsAPI is a fake API that speaks graphql-transport-ws on upgrades.
type wsAPI struct {
	mu       sync.Mutex
	got      []string      // text messages received, in order
	upgrades []http.Header // headers of the upgrades it accepted
	// extensions, when set, is a Sec-WebSocket-Extensions the API insists on.
	extensions string
	// status, when set, refuses upgrades with it.
	status int
	// leak goes into every next message, to be scrubbed.
	leak string
}

func (a *wsAPI) respond(w http.ResponseWriter, r *http.Request) {
	if !decode.IsWebSocketUpgrade(r.Method, r.Header) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"data":{}}`)
		return
	}
	if a.status != 0 {
		http.Error(w, `{"error":"not authorized"}`, a.status)
		return
	}
	c, brw, err := w.(http.Hijacker).Hijack()
	if err != nil {
		return
	}
	defer c.Close()
	a.mu.Lock()
	a.upgrades = append(a.upgrades, r.Header.Clone())
	a.mu.Unlock()
	fmt.Fprintf(c, "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\nSec-WebSocket-Protocol: graphql-transport-ws\r\n", websocket.AcceptKey(r.Header.Get("Sec-WebSocket-Key")))
	if a.extensions != "" {
		fmt.Fprintf(c, "Sec-WebSocket-Extensions: %s\r\n", a.extensions)
	}
	fmt.Fprint(c, "\r\n")
	rd, wr := websocket.NewReader(brw.Reader, true, 1<<26), websocket.NewWriter(c, false)
	for {
		m, err := rd.Next()
		if err != nil {
			return
		}
		switch m.Op {
		case websocket.OpPing:
			_ = wr.Write(websocket.Message{Op: websocket.OpPong, Data: m.Data})
			continue
		case websocket.OpClose:
			_ = wr.Write(m)
			return
		case websocket.OpBinary:
			continue
		}
		a.mu.Lock()
		a.got = append(a.got, string(m.Data))
		a.mu.Unlock()
		var msg struct{ ID, Type string }
		_ = json.Unmarshal(m.Data, &msg)
		switch msg.Type {
		case "connection_init":
			_ = wr.Write(websocket.Message{Op: websocket.OpText, Data: []byte(`{"type":"connection_ack"}`)})
		case "subscribe":
			next := fmt.Sprintf(`{"id":%q,"type":"next","payload":{"data":{"deploymentLogs":{"message":"token=%s"}}}}`, msg.ID, a.leak)
			_ = wr.Write(websocket.Message{Op: websocket.OpText, Data: []byte(next)})
			_ = wr.Write(websocket.Message{Op: websocket.OpText, Data: []byte(fmt.Sprintf(`{"id":%q,"type":"complete"}`, msg.ID))})
		}
	}
}

func (a *wsAPI) messages() []string {
	a.mu.Lock()
	defer a.mu.Unlock()
	return append([]string(nil), a.got...)
}

// wsClient is a socket opened through the proxy.
type wsClient struct {
	t    *testing.T
	conn net.Conn
	r    *websocket.Reader
	w    *websocket.Writer
	resp *http.Response
}

// dialWS opens a socket to host through the proxy's HTTP listener, offering
// permessage-deflate (which the proxy must not pass on).
func (e *env) dialWS(host, path string, hdr ...string) *wsClient {
	e.t.Helper()
	return e.dialWSProtocol(host, path, "graphql-transport-ws", hdr...)
}

// dialWSProtocol is dialWS offering subprotocol, or none when it is empty.
func (e *env) dialWSProtocol(host, path, subprotocol string, hdr ...string) *wsClient {
	e.t.Helper()
	c, err := net.Dial("tcp", e.httpAddr)
	if err != nil {
		e.t.Fatal(err)
	}
	e.t.Cleanup(func() { c.Close() })
	_ = c.SetDeadline(time.Now().Add(20 * time.Second))
	fmt.Fprintf(c, "CONNECT %s:443 HTTP/1.1\r\nHost: %s:443\r\n\r\n", host, host)
	br := bufio.NewReader(c)
	if resp, err := http.ReadResponse(br, nil); err != nil || resp.StatusCode != 200 {
		e.t.Fatalf("CONNECT: %v %v", resp, err)
	}
	tc := tls.Client(c, &tls.Config{ServerName: host, RootCAs: e.ca.Pool(), NextProtos: []string{"http/1.1"}})
	key := "dGhlIHNhbXBsZSBub25jZQ=="
	req := fmt.Sprintf("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Extensions: permessage-deflate; client_max_window_bits\r\n", path, host, key)
	if subprotocol != "" {
		req += "Sec-WebSocket-Protocol: " + subprotocol + "\r\n"
	}
	for i := 0; i+1 < len(hdr); i += 2 {
		req += hdr[i] + ": " + hdr[i+1] + "\r\n"
	}
	if _, err := io.WriteString(tc, req+"\r\n"); err != nil {
		e.t.Fatal(err)
	}
	tbr := bufio.NewReader(tc)
	resp, err := http.ReadResponse(tbr, &http.Request{Method: "GET"})
	if err != nil {
		e.t.Fatal(err)
	}
	return &wsClient{t: e.t, conn: tc, r: websocket.NewReader(tbr, false, 1<<26), w: websocket.NewWriter(tc, true), resp: resp}
}

func (c *wsClient) send(s string) {
	c.t.Helper()
	if err := c.w.Write(websocket.Message{Op: websocket.OpText, Data: []byte(s)}); err != nil {
		c.t.Fatal(err)
	}
}

func (c *wsClient) next() websocket.Message {
	c.t.Helper()
	m, err := c.r.Next()
	if err != nil {
		c.t.Fatal(err)
	}
	return m
}

const logsSubscription = `{"id":"1","type":"subscribe","payload":{"query":"subscription DeploymentLogs($deploymentId: String!) { deploymentLogs(deploymentId: $deploymentId) { message } }","variables":{"deploymentId":"dep-1"}}}`

// The stage 28a exit criterion: Railway's CLI follows logs over its
// subscription socket behind Opfence, and a mutation sent over the socket
// is decided as one sent over HTTP: blocked before it reaches Railway.
func TestWebSocketGraphQL(t *testing.T) {
	real := "rw_" + strings.Repeat("Tok3n", 8)
	placeholder, err := secrets.NewPlaceholder(real, nil)
	if err != nil {
		t.Fatal(err)
	}
	set := secrets.NewSet([]*secrets.Secret{{Provider: "railway", Name: "token", Value: real, Placeholder: placeholder}})
	api := &wsAPI{leak: real}
	e := newEnv(t, opts{secrets: set, respond: api.respond})
	c := e.dialWS("backboard.railway.com", "/graphql/v2", "Authorization", "Bearer "+placeholder)
	if c.resp.StatusCode != http.StatusSwitchingProtocols || c.resp.Header.Get("Sec-WebSocket-Protocol") != "graphql-transport-ws" {
		t.Fatalf("upgrade: %d %v", c.resp.StatusCode, c.resp.Header)
	}
	api.mu.Lock()
	up := api.upgrades[0]
	api.mu.Unlock()
	if up.Get("Authorization") != "Bearer "+real || up.Get("Sec-WebSocket-Extensions") != "" || up.Get("Sec-WebSocket-Protocol") != "graphql-transport-ws" {
		t.Fatalf("the API's upgrade: %v", up)
	}

	c.send(`{"type":"connection_init"}`)
	if m := c.next(); string(m.Data) != `{"type":"connection_ack"}` {
		t.Fatalf("ack: %s", m.Data)
	}
	c.send(logsSubscription)
	if m := c.next(); !strings.Contains(string(m.Data), "token="+placeholder) || strings.Contains(string(m.Data), real) {
		t.Fatalf("next: %s", m.Data)
	}
	if m := c.next(); !strings.Contains(string(m.Data), `"complete"`) {
		t.Fatalf("complete: %s", m.Data)
	}

	// The PocketOS call, sent over the socket.
	c.send(`{"id":"2","type":"subscribe","payload":` + pocketOS + `}`)
	m := c.next()
	var reply struct {
		ID, Type string
		Payload  []struct{ Message string }
	}
	if err := json.Unmarshal(m.Data, &reply); err != nil || reply.ID != "2" || reply.Type != "error" || len(reply.Payload) != 1 ||
		!strings.Contains(reply.Payload[0].Message, "Blocked by Opfence") || !strings.Contains(reply.Payload[0].Message, "vol-pg-data") {
		t.Fatalf("blocked reply: %s", m.Data)
	}
	// The socket stays open.
	c.send(strings.Replace(logsSubscription, `"1"`, `"3"`, 1))
	if m := c.next(); !strings.Contains(string(m.Data), `"id":"3","type":"next"`) {
		t.Fatalf("after the block: %s", m.Data)
	}
	c.next() // complete
	for _, got := range api.messages() {
		if strings.Contains(got, "volumeDelete") {
			t.Fatalf("the mutation reached the API: %s", got)
		}
	}
	if got := api.messages(); len(got) != 3 {
		t.Fatalf("the API got %q", got)
	}

	// A close goes through, and the API's answer comes back.
	_ = c.w.Write(websocket.CloseMessage(websocket.CloseNormal, "bye"))
	if m := c.next(); m.Op != websocket.OpClose {
		t.Fatalf("close: %v", m)
	}

	var upgrade, allowed, blocked bool
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) && !(upgrade && allowed && blocked) {
		for _, en := range e.entries() {
			switch {
			case en.Event == "request" && en.Status == http.StatusSwitchingProtocols && len(en.Operations) == 1 && en.Operations[0].Rule == "railway.websocket.connect":
				upgrade = len(en.Credentials) == 1
			case en.Event == "message" && en.Outcome == "forwarded" && en.Method == "subscribe" && en.Operations[0].Rule == "railway.subscription.deployment-logs":
				allowed = true
			case en.Event == "message" && en.Outcome == "blocked" && en.Operations[0].Rule == "railway.volume.delete":
				blocked = true
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	if !upgrade || !allowed || !blocked {
		t.Fatalf("audit: upgrade %v, allowed %v, blocked %v: %+v", upgrade, allowed, blocked, e.entries())
	}
}

// An approved message goes to the API; the approver sees it as a socket
// message.
func TestWebSocketApproval(t *testing.T) {
	api := &wsAPI{}
	e := newEnv(t, opts{respond: api.respond})
	a := &approveAll{}
	e.srv.cfg.Approver = a
	c := e.dialWS("backboard.railway.com", "/graphql/v2")
	c.send(`{"id":"9","type":"subscribe","payload":` + pocketOS + `}`)
	if m := c.next(); !strings.Contains(string(m.Data), `"id":"9","type":"next"`) || a.calls.Load() != 1 {
		t.Fatalf("approved: %s (%d calls)", m.Data, a.calls.Load())
	}
}

// Upgrades Opfence cannot relay are refused before anything is dialled,
// and an API that answers with an extension or a refusal is handled.
func TestWebSocketUpgradeRefused(t *testing.T) {
	api := &wsAPI{}
	e := newEnv(t, opts{respond: api.respond})
	for _, c := range []struct{ host, path, want string }{
		{"backboard.railway.com", "/graphql/internal", "does not read WebSocket messages on /graphql/internal"},
		{"api.vercel.com", "/v1/events", "does not read WebSocket messages on /v1/events for Vercel"},
	} {
		ws := e.dialWS(c.host, c.path)
		body, _ := io.ReadAll(ws.resp.Body)
		if ws.resp.StatusCode != http.StatusForbidden || !strings.Contains(string(body), c.want) {
			t.Errorf("%s%s: %d %s", c.host, c.path, ws.resp.StatusCode, body)
		}
	}
	if e.hits.Load() != 0 {
		t.Fatalf("%d upgrades reached an API", e.hits.Load())
	}

	api.extensions = "permessage-deflate"
	ws := e.dialWS("backboard.railway.com", "/graphql/v2")
	if body, _ := io.ReadAll(ws.resp.Body); ws.resp.StatusCode != http.StatusBadGateway || !strings.Contains(string(body), "extension") {
		t.Errorf("extension: %d %s", ws.resp.StatusCode, body)
	}
	api.extensions, api.status = "", http.StatusUnauthorized
	ws = e.dialWS("backboard.railway.com", "/graphql/v2")
	if body, _ := io.ReadAll(ws.resp.Body); ws.resp.StatusCode != http.StatusUnauthorized || !strings.Contains(string(body), "not authorized") {
		t.Errorf("refused: %d %s", ws.resp.StatusCode, body)
	}
}

// A message over the limit, or a frame RFC 6455 forbids, closes the socket
// with the code that says why, and tells the API the relay is going.
func TestWebSocketClosesOnBadFrames(t *testing.T) {
	old := maxWSMessage
	maxWSMessage = 1 << 10
	t.Cleanup(func() { maxWSMessage = old })
	api := &wsAPI{}
	e := newEnv(t, opts{respond: api.respond})

	c := e.dialWS("backboard.railway.com", "/graphql/v2")
	c.send(`{"type":"connection_init","payload":"` + strings.Repeat("x", 2000) + `"}`)
	if m := c.next(); m.Op != websocket.OpClose || binary.BigEndian.Uint16(m.Data) != websocket.CloseTooBig {
		t.Fatalf("too big: %v %q", m.Op, m.Data)
	}

	c = e.dialWS("backboard.railway.com", "/graphql/v2")
	// A text frame with a reserved bit set (no extension was negotiated).
	frame := []byte{0xC1, 0x80 | 2, 1, 2, 3, 4, 'h' ^ 1, 'i' ^ 2}
	if _, err := c.conn.Write(frame); err != nil {
		t.Fatal(err)
	}
	if m := c.next(); m.Op != websocket.OpClose || binary.BigEndian.Uint16(m.Data) != websocket.CloseProtocolError {
		t.Fatalf("reserved bit: %v %q", m.Op, m.Data)
	}
	// A message Opfence cannot read is unknown, and with no one to ask it
	// is blocked; a graphql-ws message without an id closes the socket.
	c = e.dialWS("backboard.railway.com", "/graphql/v2")
	c.send(`{"type":"mystery"}`)
	if m := c.next(); m.Op != websocket.OpClose || binary.BigEndian.Uint16(m.Data) != websocket.ClosePolicyViolation || !strings.Contains(string(m.Data), "Blocked by Opfence") {
		t.Fatalf("unknown message: %v %q", m.Op, m.Data)
	}
	for _, got := range api.messages() {
		if strings.Contains(got, "mystery") || strings.Contains(got, "xxxx") {
			t.Fatalf("the API got %s", got)
		}
	}
}
