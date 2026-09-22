package decode

import (
	"encoding/json"
	"net/http"
	"net/url"
	"strings"
	"testing"

	"github.com/rakeshnitb23/opfence/internal/request"
)

func upgrade(path string) *request.Request {
	h := http.Header{}
	h.Set("Upgrade", "websocket")
	h.Set("Connection", "Upgrade")
	h.Set("Sec-WebSocket-Key", "dGhlIHNhbXBsZSBub25jZQ==")
	h.Set("Authorization", "Bearer opf_x")
	u, _ := url.Parse(path)
	return &request.Request{Method: "GET", Host: "api.acme.dev", Path: u.EscapedPath(), Query: u.Query(), Header: h}
}

var wsHints = Hints{GraphQLPaths: []string{"/graphql"}, WebSocket: []WebSocketPath{{Path: "/graphql", Protocol: WSGraphQL}}}

func TestWebSocketUpgradeDecodes(t *testing.T) {
	if !IsWebSocketUpgrade("GET", http.Header{"Upgrade": {"h2c, WebSocket"}}) || IsWebSocketUpgrade("POST", http.Header{"Upgrade": {"websocket"}}) ||
		IsWebSocketUpgrade("GET", http.Header{"Upgrade": {"h2c"}}) {
		t.Fatal("IsWebSocketUpgrade")
	}
	ops := Decode(upgrade("/graphql/./?token=x"), wsHints)
	if len(ops) != 1 || ops[0].Protocol != WebSocket || ops[0].Method != WSConnect || ops[0].Path != "/graphql" || ops[0].Error != "" {
		t.Fatalf("%+v", ops)
	}
	if q, _ := ops[0].Args["query"].(map[string]any); q["token"] != "x" {
		t.Fatalf("query %v", ops[0].Args)
	}
	// Not read as a GraphQL GET on the same path, and an unlisted path
	// cannot be read.
	if ops := Decode(upgrade("/other"), wsHints); ops[0].Error == "" || ops[0].Protocol != WebSocket {
		t.Fatalf("%+v", ops)
	}
}

func session(t *testing.T, sub string) WSSession {
	t.Helper()
	s := NewWSSession(WSGraphQL, sub, upgrade("/graphql"), wsHints)
	if s == nil {
		t.Fatal("no session")
	}
	return s
}

func text(s string) WSMessage { return WSMessage{Data: []byte(s)} }

func TestGraphQLWSSession(t *testing.T) {
	s := session(t, "graphql-transport-ws")
	for _, m := range []string{`{"type":"connection_init","payload":{}}`, `{"type":"ping"}`, `{"type":"pong"}`, `{"id":"1","type":"complete"}`} {
		if st := s.Client(text(m)); st.Decides() || len(st.Forward) != 1 {
			t.Errorf("%s: %+v", m, st)
		}
	}
	st := s.Client(text(`{"id":"7","type":"subscribe","payload":{"query":"mutation { dbWipe(id: \"d\") }"}}`))
	if st.Request == nil || st.Kind != "subscribe" || st.Request.Method != "POST" || st.Request.Path != "/graphql" {
		t.Fatalf("%+v", st)
	}
	if st.Request.Header.Get("Upgrade") != "" || st.Request.Header.Get("Authorization") != "Bearer opf_x" || st.Request.ContentType() != "application/json" {
		t.Fatalf("headers %v", st.Request.Header)
	}
	ops := Decode(st.Request, wsHints)
	if len(ops) != 1 || ops[0].Protocol != GraphQL || ops[0].GraphQLType != "mutation" || ops[0].Field != "dbWipe" {
		t.Fatalf("%+v", ops)
	}
	replies, closeSocket := s.Blocked(st, "Blocked by Opfence: no.")
	var reply struct {
		ID, Type string
		Payload  []struct{ Message string }
	}
	if closeSocket || len(replies) != 1 || json.Unmarshal(replies[0].Data, &reply) != nil || reply.ID != "7" || reply.Type != "error" || reply.Payload[0].Message != "Blocked by Opfence: no." {
		t.Fatalf("%v %v", closeSocket, replies)
	}
	// The older protocol's names, and its error payload is an object.
	if st := s.Client(text(`{"id":"1","type":"start","payload":{"query":"{ a }"}}`)); st.Request != nil || st.Ops[0].Error == "" {
		t.Fatalf("start under graphql-transport-ws: %+v", st)
	}
	legacy := session(t, "graphql-ws")
	st = legacy.Client(text(`{"id":"1","type":"start","payload":{"query":"subscription { a }"}}`))
	if st.Request == nil {
		t.Fatalf("%+v", st)
	}
	replies, _ = legacy.Blocked(st, "no")
	if string(replies[0].Data) != `{"id":"1","payload":{"message":"no"},"type":"error"}` {
		t.Fatalf("%s", replies[0].Data)
	}
	if st := legacy.Client(text(`{"id":"1","type":"stop"}`)); st.Decides() {
		t.Fatalf("stop: %+v", st)
	}
}

// What the session cannot read is an operation the engine classifies as
// unknown; without an id the socket closes.
func TestGraphQLWSSessionFailsClosed(t *testing.T) {
	s := session(t, "graphql-transport-ws")
	for _, m := range []WSMessage{
		text(`not json`), text(`{"id":"1"}`), text(`{"type":"mystery"}`), text(`{"id":1,"type":"subscribe"}`),
		{Binary: true, Data: []byte(`{"type":"ping"}`)},
	} {
		st := s.Client(m)
		if st.Request != nil || len(st.Ops) != 1 || st.Ops[0].Error == "" || st.Ops[0].Protocol != WebSocket {
			t.Errorf("%s: %+v", m.Data, st)
		}
		if _, closeSocket := s.Blocked(st, "no"); !closeSocket {
			t.Errorf("%s: blocked without closing", m.Data)
		}
	}
	// A payload too large to read is a request whose body cannot be read.
	big := `{"id":"1","type":"subscribe","payload":{"query":"` + strings.Repeat("a", request.MaxBody) + `"}}`
	st := s.Client(text(big))
	if st.Request == nil || st.Request.BodyErr == nil {
		t.Fatalf("%+v", st.Request)
	}
	if ops := Decode(st.Request, wsHints); ops[0].Error == "" {
		t.Fatalf("%+v", ops)
	}
	// A subscribe without a payload has no query.
	if ops := Decode(s.Client(text(`{"id":"1","type":"subscribe"}`)).Request, wsHints); ops[0].Error == "" {
		t.Fatalf("%+v", ops)
	}
}

// No message makes a session panic, and whatever it decides is a socket
// operation or a request on the socket's path.
func FuzzWSSessions(f *testing.F) {
	f.Add(`{"id":"1","type":"subscribe","payload":{"query":"{ a }"}}`, false, uint8(0))
	f.Add(`["1","1","realtime:x","phx_join",{"access_token":"t"}]`, false, uint8(1))
	f.Add("\x03\x01\x01\x01\x01\x00\x01abcd{}", true, uint8(1))
	f.Add(`{"type":"request","request_id":1,"request":{"type":"batch","batch":{"steps":[{"stmt":{"sql_id":1}}]}}}`, false, uint8(2))
	f.Fuzz(func(t *testing.T, data string, binary bool, which uint8) {
		protos := []string{WSGraphQL, WSPhoenix, WSHrana}
		h := upgrade("/s?vsn=2.0.0")
		h.Query = url.Values{"vsn": {"2.0.0"}}
		s := NewWSSession(protos[int(which)%len(protos)], "graphql-transport-ws", h, wsHints)
		for i := 0; i < 2; i++ {
			st := s.Client(WSMessage{Binary: binary, Data: []byte(data)})
			for _, op := range st.Ops {
				if op.Protocol != WebSocket || op.Path != "/s" {
					t.Fatalf("%+v", op)
				}
			}
			if st.Request != nil && (st.Request.Path != "/s" || st.Request.Method != "POST") {
				t.Fatalf("%+v", st.Request)
			}
			s.Forwarded(st)
			s.Blocked(st, "no")
			s.Server(WSMessage{Binary: binary, Data: []byte(data)})
		}
	})
}
