package decode

import (
	"bytes"
	"encoding/json"
	"strings"

	"github.com/rakeshnitb23/opfence/internal/request"
)

// WSPhoenix is the Phoenix channels protocol, as Supabase Realtime speaks
// it: serializer 1.0.0 (JSON objects) or 2.0.0 (JSON arrays, and binary
// frames for broadcasts), chosen by the upgrade's vsn parameter.
const WSPhoenix = "phoenix"

// Phoenix message names rules can match.
const (
	PhoenixJoin      = "join"      // phx_join: subscribe to a channel; args topic, config
	PhoenixBroadcast = "broadcast" // send a broadcast; args topic, event, payload
	PhoenixPresence  = "presence"  // track or untrack presence; args topic, event
)

// phoenixWS reads Phoenix channel messages (docs/ARCHITECTURE.md §3.5).
type phoenixWS struct {
	path string
	v2   bool
}

func newPhoenixWS(handshake *request.Request) *phoenixWS {
	return &phoenixWS{path: handshake.Path, v2: strings.HasPrefix(handshake.Query.Get("vsn"), "2.")}
}

// phoenixMsg is one message, in either serializer.
type phoenixMsg struct {
	joinRef, ref json.RawMessage
	topic, event string
	payload      any
	binary       bool // a 2.0.0 user broadcast push
}

func (p *phoenixWS) Client(m WSMessage) WSStep {
	msg, ok := p.read(m)
	if !ok {
		return wsFailed(p.path, "message", "not a Realtime message Opfence can read", m)
	}
	pass := WSStep{Kind: msg.event, Forward: []WSMessage{m}, text: !m.Binary}
	pass.id = string(msg.ref)
	payload, _ := msg.payload.(map[string]any)
	switch msg.event {
	case "heartbeat", "phx_leave":
		return pass
	case "access_token":
		// A new token for the channel: swapped like the upgrade's key.
		pass.Swap = phoenixTokens(payload)
		return pass
	case "phx_join":
		cfg, _ := payload["config"].(map[string]any)
		args := map[string]any{"topic": msg.topic, "config": cfg}
		s := p.step(PhoenixJoin, msg, args, m)
		s.Swap = phoenixTokens(payload)
		return s
	case "broadcast":
		ev, _ := payload["event"].(string)
		return p.step(PhoenixBroadcast, msg, map[string]any{"topic": msg.topic, "event": ev, "payload": payload["payload"]}, m)
	case "presence":
		ev, _ := payload["event"].(string)
		return p.step(PhoenixPresence, msg, map[string]any{"topic": msg.topic, "event": ev}, m)
	}
	s := wsFailed(p.path, msg.event, "a Realtime event Opfence does not know", m)
	s.id, s.text = string(msg.ref), !m.Binary
	return s
}

func (p *phoenixWS) step(name string, msg phoenixMsg, args map[string]any, m WSMessage) WSStep {
	return WSStep{
		Kind: msg.event, Ops: []Operation{{Protocol: WebSocket, Method: name, Path: p.path, Args: args}},
		Body: m.Data, Forward: []WSMessage{m}, id: string(msg.ref), text: !m.Binary, phoenix: &msg,
	}
}

// phoenixTokens returns the access token a join or token update carries.
func phoenixTokens(payload map[string]any) []string {
	if t, ok := payload["access_token"].(string); ok && t != "" {
		return []string{t}
	}
	return nil
}

// read parses a message in the session's serializer.
func (p *phoenixWS) read(m WSMessage) (phoenixMsg, bool) {
	if m.Binary {
		if !p.v2 {
			return phoenixMsg{}, false
		}
		return readPhoenixBinary(m.Data)
	}
	var msg phoenixMsg
	if p.v2 {
		var arr []json.RawMessage
		if json.Unmarshal(m.Data, &arr) != nil || len(arr) != 5 {
			return msg, false
		}
		msg.joinRef, msg.ref = arr[0], arr[1]
		if json.Unmarshal(arr[2], &msg.topic) != nil || json.Unmarshal(arr[3], &msg.event) != nil {
			return msg, false
		}
		v, err := parseJSON(arr[4])
		if err != nil {
			return msg, false
		}
		msg.payload = v
	} else {
		var obj struct {
			Topic   *string         `json:"topic"`
			Event   *string         `json:"event"`
			Payload json.RawMessage `json:"payload"`
			Ref     json.RawMessage `json:"ref"`
			JoinRef json.RawMessage `json:"join_ref"`
		}
		if json.Unmarshal(m.Data, &obj) != nil || obj.Topic == nil || obj.Event == nil {
			return msg, false
		}
		msg.topic, msg.event, msg.ref, msg.joinRef = *obj.Topic, *obj.Event, obj.Ref, obj.JoinRef
		if len(obj.Payload) > 0 {
			v, err := parseJSON(obj.Payload)
			if err != nil {
				return msg, false
			}
			msg.payload = v
		}
	}
	if _, isObj := msg.payload.(map[string]any); msg.payload != nil && !isObj {
		return msg, false
	}
	// A duplicate key anywhere would be read one way here and another by
	// the server: the strict reader above refuses them in the payload, and
	// the envelope is checked again here.
	if _, err := parseJSON(m.Data); err != nil {
		return msg, false
	}
	return msg, true
}

// readPhoenixBinary reads Realtime's binary user broadcast push (kind 3):
// lengths of the join ref, ref, topic, event and metadata, the payload's
// encoding (0 binary, 1 JSON), the strings, then the payload.
func readPhoenixBinary(b []byte) (phoenixMsg, bool) {
	const kindUserBroadcastPush, header = 3, 7
	if len(b) < header || b[0] != kindUserBroadcastPush {
		return phoenixMsg{}, false
	}
	lens := []int{int(b[1]), int(b[2]), int(b[3]), int(b[4]), int(b[5])}
	off := header
	parts := make([]string, len(lens))
	for i, n := range lens {
		if off+n > len(b) {
			return phoenixMsg{}, false
		}
		parts[i] = string(b[off : off+n])
		off += n
	}
	ref, _ := json.Marshal(parts[1])
	joinRef, _ := json.Marshal(parts[0])
	msg := phoenixMsg{joinRef: joinRef, ref: ref, topic: parts[2], event: "broadcast", binary: true}
	inner := map[string]any{"type": "broadcast", "event": parts[3]}
	switch b[6] {
	case 1:
		v, err := parseJSON(b[off:])
		if err != nil {
			return phoenixMsg{}, false
		}
		inner["payload"] = v
	case 0:
		inner["payload"] = map[string]any{} // bytes Opfence does not read
	default:
		return phoenixMsg{}, false
	}
	msg.payload = inner
	return msg, true
}

func (p *phoenixWS) Forwarded(WSStep) {}

func (p *phoenixWS) Server(m WSMessage) []WSMessage { return []WSMessage{m} }

// Blocked answers the push with an error reply for its ref, as the server
// does when a channel refuses it; the socket stays open. A message with no
// ref closes it.
func (p *phoenixWS) Blocked(s WSStep, reason string) ([]WSMessage, bool) {
	if s.id == "" || s.id == "null" || s.id == `""` {
		return nil, true
	}
	topic, joinRef := "", json.RawMessage("null")
	if s.phoenix != nil {
		topic = s.phoenix.topic
		if len(s.phoenix.joinRef) > 0 {
			joinRef = s.phoenix.joinRef
		}
	}
	payload := map[string]any{"status": "error", "response": map[string]string{"reason": reason}}
	var b []byte
	if p.v2 {
		t, _ := json.Marshal(topic)
		pl, _ := json.Marshal(payload)
		b = bytes.Join([][]byte{joinRef, []byte(s.id), t, []byte(`"phx_reply"`), pl}, []byte(","))
		b = append(append([]byte("["), b...), ']')
	} else {
		b, _ = json.Marshal(map[string]any{"topic": topic, "event": "phx_reply", "payload": payload, "ref": json.RawMessage(s.id), "join_ref": joinRef})
	}
	return []WSMessage{{Data: b}}, false
}
