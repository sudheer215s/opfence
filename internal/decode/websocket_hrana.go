package decode

import (
	"encoding/json"
	"fmt"

	"github.com/rakeshnitb23/opfence/internal/request"
)

// WSHrana is libSQL's Hrana protocol over WebSocket (hrana1 to hrana3 as
// JSON; the protobuf form is binary and not read), which libSQL clients
// speak on wss:// URLs.
const WSHrana = "hrana"

// HranaRequest is the message name of a Hrana request; its args hold the
// request as a pipeline body, {"requests": [request]}, which classify's
// libsql format reads.
const HranaRequest = "request"

// hranaWS reads Hrana requests (docs/ARCHITECTURE.md §3.5). SQL a
// connection stores (store_sql) is kept once forwarded, so a later request
// that runs it by its sql_id is decided by the text it runs.
type hranaWS struct {
	path   string
	stored map[string]string // sql_id → SQL, for texts forwarded on this connection
	size   int               // bytes in stored
}

// maxHranaStored bounds the SQL a connection keeps; past it, texts are not
// kept, and requests that run them by id are unknown.
const maxHranaStored = 8 << 20

func newHranaWS(handshake *request.Request) *hranaWS {
	return &hranaWS{path: handshake.Path, stored: map[string]string{}}
}

func (h *hranaWS) Client(m WSMessage) WSStep {
	if m.Binary {
		return wsFailed(h.path, "message", "a binary Hrana message (protobuf), which Opfence does not read", m)
	}
	v, err := parseJSON(m.Data)
	msg, isObj := v.(map[string]any)
	if err != nil || !isObj {
		return wsFailed(h.path, "message", "not a Hrana message", m)
	}
	pass := WSStep{Kind: fmt.Sprint(msg["type"]), Forward: []WSMessage{m}, text: true}
	switch msg["type"] {
	case "hello":
		if jwt, ok := msg["jwt"].(string); ok && jwt != "" {
			pass.Swap = []string{jwt}
		}
		return pass
	case "request":
	default:
		return wsFailed(h.path, pass.Kind, "a Hrana message Opfence does not know", m)
	}
	id, _ := json.Marshal(msg["request_id"])
	req, ok := msg["request"].(map[string]any)
	if !ok || msg["request_id"] == nil {
		s := wsFailed(h.path, HranaRequest, "a Hrana request without a request or its id", m)
		s.id = string(id)
		return s
	}
	kind, _ := req["type"].(string)
	pass.Kind, pass.id = kind, string(id)
	switch kind {
	case "open_stream", "close_stream", "close_sql", "close_cursor", "fetch_cursor", "get_autocommit", "describe":
		// Nothing runs: describe only prepares the statement.
		pass.hrana = req
		return pass
	case "store_sql":
		// Stored, not run; kept once forwarded, for the request that runs it.
		if _, isStr := req["sql"].(string); !isStr || req["sql_id"] == nil {
			break
		}
		pass.hrana = req
		return pass
	case "execute", "batch", "sequence", "open_cursor":
		inner := h.resolve(req)
		if kind == "open_cursor" {
			inner = map[string]any{"type": "batch", "batch": inner["batch"]}
		}
		return WSStep{
			Kind: kind, Body: m.Data, Forward: []WSMessage{m}, id: string(id), text: true,
			Ops: []Operation{{Protocol: WebSocket, Method: HranaRequest, Path: h.path,
				Args: map[string]any{"request": map[string]any{"requests": []any{inner}}}}},
		}
	}
	s := wsFailed(h.path, HranaRequest, "a Hrana request Opfence does not know", m)
	s.id = string(id)
	return s
}

// resolve returns a copy of req with every sql_id stored on this
// connection replaced by its text. An id it does not know stays, and the
// libSQL reader then finds SQL it cannot see.
func (h *hranaWS) resolve(req map[string]any) map[string]any {
	stmt := func(v any) any {
		st, ok := v.(map[string]any)
		if !ok || st["sql_id"] == nil || st["sql"] != nil {
			// Both sql and sql_id: left for the reader, which then finds an
			// id it cannot see.
			return v
		}
		text, known := h.stored[fmt.Sprint(st["sql_id"])]
		if !known {
			return v
		}
		out := map[string]any{}
		for k, x := range st {
			if k != "sql_id" {
				out[k] = x
			}
		}
		out["sql"] = text
		return out
	}
	out := map[string]any{}
	for k, v := range req {
		out[k] = v
	}
	switch req["type"] {
	case "execute":
		out["stmt"] = stmt(req["stmt"])
	case "sequence":
		out = stmt(req).(map[string]any)
	case "batch", "open_cursor":
		if b, ok := req["batch"].(map[string]any); ok {
			nb := map[string]any{}
			for k, v := range b {
				nb[k] = v
			}
			if steps, ok := b["steps"].([]any); ok {
				ns := make([]any, len(steps))
				for i, s := range steps {
					sm, ok := s.(map[string]any)
					if !ok {
						ns[i] = s
						continue
					}
					c := map[string]any{}
					for k, v := range sm {
						c[k] = v
					}
					c["stmt"] = stmt(sm["stmt"])
					ns[i] = c
				}
				nb["steps"] = ns
			}
			out["batch"] = nb
		}
	}
	return out
}

func (h *hranaWS) Forwarded(s WSStep) {
	switch s.hrana["type"] {
	case "store_sql":
		id, text := fmt.Sprint(s.hrana["sql_id"]), s.hrana["sql"].(string)
		h.size -= len(h.stored[id])
		delete(h.stored, id)
		if h.size+len(text) <= maxHranaStored {
			h.stored[id] = text
			h.size += len(text)
		}
	case "close_sql":
		id := fmt.Sprint(s.hrana["sql_id"])
		h.size -= len(h.stored[id])
		delete(h.stored, id)
	}
}

func (h *hranaWS) Server(m WSMessage) []WSMessage { return []WSMessage{m} }

// Blocked answers the request with response_error for its id, after which
// the stream carries on; a message with no id closes the socket.
func (h *hranaWS) Blocked(s WSStep, reason string) ([]WSMessage, bool) {
	if s.id == "" || s.id == "null" {
		return nil, true
	}
	b, _ := json.Marshal(map[string]any{"type": "response_error", "request_id": json.RawMessage(s.id),
		"error": map[string]string{"message": reason, "code": "OPFENCE_BLOCKED"}})
	return []WSMessage{{Data: b}}, false
}
