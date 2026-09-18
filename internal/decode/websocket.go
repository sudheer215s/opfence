package decode

import (
	"encoding/json"
	"net/http"
	"net/url"
	"strings"

	"github.com/rakeshnitb23/opfence/internal/request"
)

// WebSocket message protocols a provider's websocket paths can speak
// (docs/ARCHITECTURE.md §3.5).
const (
	// WSGraphQL is GraphQL over WebSocket: graphql-transport-ws, and the
	// older graphql-ws of subscriptions-transport-ws.
	WSGraphQL = "graphql-ws"
)

// WSConnect is the message name of the upgrade request itself.
const WSConnect = "connect"

// WebSocketMessages lists, for each protocol, the message names rules can
// match. Messages decided by other rules (GraphQL operations) are not
// listed; every protocol has connect.
var WebSocketMessages = map[string][]string{
	WSGraphQL:  {WSConnect},
	WSPostgres: {WSConnect, PGQuery, PGCancel},
	WSPhoenix:  {WSConnect, PhoenixJoin, PhoenixBroadcast, PhoenixPresence},
	WSHrana:    {WSConnect, HranaRequest},
}

// WebSocketSubprotocols lists, for each protocol, the subprotocols
// (Sec-WebSocket-Protocol) whose messages Opfence reads. The relay offers
// the API only these, so it cannot pick one Opfence would not read (Hrana's
// protobuf form); a protocol with none listed offers none.
var WebSocketSubprotocols = map[string][]string{
	WSGraphQL: {"graphql-transport-ws", "graphql-ws"},
	WSHrana:   {"hrana3", "hrana2", "hrana1"},
}

// ReadableSubprotocols returns the subprotocols of offered (a
// Sec-WebSocket-Protocol value) that protocol's session reads, in the
// client's order.
func ReadableSubprotocols(protocol string, offered []string) []string {
	var out []string
	for _, v := range offered {
		for _, tok := range strings.Split(v, ",") {
			tok = strings.TrimSpace(tok)
			for _, ok := range WebSocketSubprotocols[protocol] {
				if tok == ok {
					out = append(out, tok)
				}
			}
		}
	}
	return out
}

// IsWebSocketUpgrade reports whether a request asks to open a WebSocket:
// a GET whose Upgrade header names websocket.
func IsWebSocketUpgrade(method string, h http.Header) bool {
	if method != http.MethodGet {
		return false
	}
	for _, v := range h.Values("Upgrade") {
		for _, tok := range strings.Split(v, ",") {
			if strings.EqualFold(strings.TrimSpace(tok), "websocket") {
				return true
			}
		}
	}
	return false
}

// WebSocketPathFor returns the provider's websocket path that rawPath is,
// compared after dot segments are resolved, as GraphQL paths are.
func WebSocketPathFor(rawPath string, paths []WebSocketPath) (WebSocketPath, bool) {
	segs, ok := request.NormalizePath(rawPath)
	if !ok {
		return WebSocketPath{}, false
	}
	norm := "/" + joinSegs(segs)
	for _, p := range paths {
		ps, ok := request.NormalizePath(p.Path)
		if ok && norm == "/"+joinSegs(ps) {
			return p, true
		}
	}
	return WebSocketPath{}, false
}

// decodeWebSocketConnect reads an upgrade request: the operation of opening
// the socket, with the query's parameters as for REST. An upgrade on a path
// the provider does not list cannot be read further.
func decodeWebSocketConnect(r *request.Request, paths []WebSocketPath) Operation {
	wp, ok := WebSocketPathFor(r.Path, paths)
	if !ok {
		return failed(r, WebSocket, "a WebSocket upgrade on a path where the provider takes none")
	}
	query, err := formArgs(r.Query)
	if err != nil {
		query = valuesToMap(r.Query)
	}
	args := map[string]any{"query": query}
	if wp.Protocol == WSPostgres {
		// The database is named only once the socket carries its startup
		// message; the host is known now.
		args["connection"] = map[string]any{"host": r.Host}
	}
	return Operation{Protocol: WebSocket, Method: WSConnect, Path: wp.Path, Args: args}
}

// WSMessage is a WebSocket data message.
type WSMessage struct {
	Binary bool
	Data   []byte
}

// WSStep is what one message from the agent asks for.
type WSStep struct {
	// Kind names the message for the audit log: subscribe, query.
	Kind string
	// Request is set when the message carries a request the engine
	// decides as if it had been sent on its own (a GraphQL operation).
	Request *request.Request
	// Ops are the operations to decide otherwise. A step with neither
	// carries protocol control only and passes.
	Ops []Operation
	// Body is what an approval of the step binds to.
	Body []byte
	// Forward is what goes to the API when the step is allowed.
	Forward []WSMessage
	// Swap lists credentials the messages carry where the protocol puts
	// its token (a Realtime join's access_token, a Hrana hello's jwt): the
	// proxy swaps their placeholders in, as it does in auth headers.
	Swap []string

	id   string // the protocol's id for the message, for error replies
	text bool   // the message was text, for replies in kind
	raw  bool   // once forwarded, the rest of the stream cannot be read
	ssl  bool   // a Postgres SSLRequest goes to the server

	phoenix *phoenixMsg    // the Realtime message, for its error reply
	hrana   map[string]any // the Hrana request, for state kept once forwarded
}

// Decides reports whether the step has anything to decide.
func (s WSStep) Decides() bool { return s.Request != nil || len(s.Ops) > 0 }

// WSSession reads one WebSocket connection's messages. It does no I/O; the
// proxy relays what it returns, and the fixture runner replays it. Client,
// Forwarded and Blocked are called from one goroutine and Server from
// another, so a session guards any state they share.
type WSSession interface {
	// Client reads a message the agent sent.
	Client(m WSMessage) WSStep
	// Forwarded tells the session a step went to the API, so state that
	// later messages depend on (a stored statement) counts only then.
	Forwarded(s WSStep)
	// Server reads a message the API sent and returns what to pass on.
	Server(m WSMessage) []WSMessage
	// Blocked returns what to tell the agent about a step that is not
	// forwarded, and whether the socket must close: when the protocol has
	// no error reply for it, or the connection's state would be wrong.
	Blocked(s WSStep, reason string) (replies []WSMessage, closeSocket bool)
}

// NewWSSession returns the session for a protocol, or nil when Opfence
// does not read it. subprotocol is the one the API accepted
// (Sec-WebSocket-Protocol), handshake the upgrade as decided, h the
// provider's hints.
func NewWSSession(protocol, subprotocol string, handshake *request.Request, h Hints) WSSession {
	switch protocol {
	case WSGraphQL:
		return &graphqlWS{legacy: subprotocol == "graphql-ws", handshake: handshake}
	case WSPostgres:
		return newPGWS(handshake)
	case WSPhoenix:
		return newPhoenixWS(handshake)
	case WSHrana:
		return newHranaWS(handshake)
	}
	return nil
}

// wsFailed is a message the session could not read: an operation the
// engine classifies as unknown.
func wsFailed(path, kind, msg string, m WSMessage) WSStep {
	return WSStep{
		Kind: kind, Ops: []Operation{{Protocol: WebSocket, Method: kind, Path: path, Error: msg}},
		Body: m.Data, Forward: []WSMessage{m}, text: !m.Binary,
	}
}

// graphqlWS reads graphql-transport-ws and the older graphql-ws. Their
// subscribe and start messages carry a GraphQL request, decided by the
// provider's GraphQL rules exactly as if it had been posted to the
// socket's path; the rest is protocol control.
type graphqlWS struct {
	legacy    bool
	handshake *request.Request
}

func (g *graphqlWS) Client(m WSMessage) WSStep {
	path := g.handshake.Path
	var msg struct {
		Type    string          `json:"type"`
		ID      json.RawMessage `json:"id"`
		Payload json.RawMessage `json:"payload"`
	}
	if m.Binary || json.Unmarshal(m.Data, &msg) != nil || msg.Type == "" {
		return wsFailed(path, "message", "not a GraphQL over WebSocket message", m)
	}
	id := ""
	if len(msg.ID) > 0 {
		if err := json.Unmarshal(msg.ID, &id); err != nil {
			return wsFailed(path, msg.Type, "the message's id is not a string", m)
		}
	}
	pass := WSStep{Kind: msg.Type, Forward: []WSMessage{m}, id: id, text: true}
	switch msg.Type {
	case "connection_init", "ping", "pong", "complete":
		return pass
	case "stop", "connection_terminate":
		if g.legacy {
			return pass
		}
	case "subscribe":
		if g.legacy {
			break
		}
		return g.operation(msg.Type, id, msg.Payload, m)
	case "start":
		if !g.legacy {
			break
		}
		return g.operation(msg.Type, id, msg.Payload, m)
	}
	s := wsFailed(path, msg.Type, "a GraphQL over WebSocket message Opfence does not know", m)
	s.id = id
	return s
}

// operation decides a subscribe or start payload as a GraphQL request
// posted to the socket's path, with the upgrade's headers.
func (g *graphqlWS) operation(kind, id string, payload json.RawMessage, m WSMessage) WSStep {
	h := g.handshake.Header.Clone()
	for _, k := range []string{"Upgrade", "Connection", "Sec-Websocket-Key", "Sec-Websocket-Version", "Sec-Websocket-Protocol", "Sec-Websocket-Extensions"} {
		h.Del(k)
	}
	h.Set("Content-Type", "application/json")
	req := &request.Request{Method: http.MethodPost, Host: g.handshake.Host, Port: g.handshake.Port, Path: g.handshake.Path, Query: url.Values{}, Header: h}
	if len(payload) > request.MaxBody {
		req.BodyErr, req.Prefix = request.ErrBodyTooLarge, payload[:request.MaxBody]
	} else {
		req.Body = payload
	}
	return WSStep{Kind: kind, Request: req, Body: payload, Forward: []WSMessage{m}, id: id, text: true}
}

func (g *graphqlWS) Forwarded(WSStep) {}

func (g *graphqlWS) Server(m WSMessage) []WSMessage { return []WSMessage{m} }

// Blocked answers the operation with an error for its id, after which the
// API knows nothing of it and the socket stays open. A message with no id
// closes the socket, as the protocol's servers do.
func (g *graphqlWS) Blocked(s WSStep, reason string) ([]WSMessage, bool) {
	if s.id == "" {
		return nil, true
	}
	var payload any = []map[string]string{{"message": reason}}
	if g.legacy {
		payload = map[string]string{"message": reason}
	}
	b, _ := json.Marshal(map[string]any{"id": s.id, "type": "error", "payload": payload})
	return []WSMessage{{Data: b}}, false
}
