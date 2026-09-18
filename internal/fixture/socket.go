package fixture

import (
	"bytes"
	"fmt"
	"strconv"
	"strings"

	"github.com/rakeshnitb23/opfence/internal/catalog"
	"github.com/rakeshnitb23/opfence/internal/decode"
	"github.com/rakeshnitb23/opfence/internal/engine"
	"github.com/rakeshnitb23/opfence/internal/request"
)

// Socket is a .ws fixture: a WebSocket upgrade and the messages the agent
// sends on the socket, in order.
//
// The upgrade is written like a .http fixture's request. Each message
// starts with a line ">>> text" or ">>> binary". A text message is the
// lines that follow, up to the next message. A binary message is written
// as Go string literals, one or more per line, joined ("Q\x00\x00\x00\x0d").
// Lines starting with # are comments in both.
type Socket struct {
	Upgrade  *request.Request
	Messages []decode.WSMessage
}

// ParseSocket parses a .ws fixture.
func ParseSocket(data []byte) (*Socket, error) {
	head, rest, found := cutMessages(data)
	if !found {
		return nil, fmt.Errorf("socket fixture has no messages (a line starting with >>>)")
	}
	req, _, err := request.ParseFixture(head)
	if err != nil {
		return nil, err
	}
	s := &Socket{Upgrade: req}
	for _, block := range bytes.Split(rest, []byte("\n>>> ")) {
		kind, body, _ := bytes.Cut(block, []byte("\n"))
		var lines []string
		for _, l := range strings.Split(string(body), "\n") {
			if !strings.HasPrefix(strings.TrimSpace(l), "#") {
				lines = append(lines, strings.TrimSuffix(l, "\r"))
			}
		}
		switch strings.TrimSpace(string(kind)) {
		case "text":
			s.Messages = append(s.Messages, decode.WSMessage{Data: []byte(strings.TrimRight(strings.Join(lines, "\n"), "\n"))})
		case "binary":
			var b []byte
			for _, l := range lines {
				l = strings.TrimSpace(l)
				for l != "" {
					q, err := strconv.QuotedPrefix(l)
					if err != nil {
						return nil, fmt.Errorf("binary message: %q is not a Go string literal", l)
					}
					v, _ := strconv.Unquote(q)
					b = append(b, v...)
					l = strings.TrimSpace(l[len(q):])
				}
			}
			s.Messages = append(s.Messages, decode.WSMessage{Binary: true, Data: b})
		default:
			return nil, fmt.Errorf("message kind %q must be text or binary", kind)
		}
	}
	return s, nil
}

// cutMessages splits a fixture at its first message line.
func cutMessages(data []byte) (head, rest []byte, found bool) {
	data = bytes.ReplaceAll(data, []byte("\r\n"), []byte("\n"))
	if bytes.HasPrefix(data, []byte(">>> ")) {
		return nil, data[4:], true
	}
	i := bytes.Index(data, []byte("\n>>> "))
	if i < 0 {
		return data, nil, false
	}
	return data[:i+1], data[i+5:], true
}

// Replay decides a socket fixture's messages one by one, as the proxy
// would, each earlier one as if it had been forwarded, and returns the
// decision on the last.
func Replay(eng *engine.Engine, c *catalog.Catalog, s *Socket) (engine.Result, error) {
	steps, err := Steps(eng, c, s)
	if err != nil {
		return engine.Result{}, err
	}
	last := steps[len(steps)-1]
	if !last.Step.Decides() {
		return engine.Result{}, fmt.Errorf("the last message (%s) is protocol control, which passes undecided", last.Step.Kind)
	}
	return last.Result, nil
}

// SocketStep is one message of a socket fixture and its decision, when it
// has one to make.
type SocketStep struct {
	Step   decode.WSStep
	Result engine.Result
}

// Steps decides every message of a socket fixture, each as if the ones
// before it had been forwarded.
func Steps(eng *engine.Engine, c *catalog.Catalog, s *Socket) ([]SocketStep, error) {
	up := s.Upgrade
	if !decode.IsWebSocketUpgrade(up.Method, up.Header) {
		return nil, fmt.Errorf("a socket fixture's request must be a WebSocket upgrade")
	}
	p := c.ProviderForHost(up.Host)
	if p == nil {
		return nil, fmt.Errorf("%s is not in the catalog", up.Host)
	}
	h := p.Hints(up.Host)
	wp, ok := decode.WebSocketPathFor(up.Path, h.WebSocket)
	if !ok {
		return nil, fmt.Errorf("%s takes no WebSocket upgrades on %s", p.ID, up.Path)
	}
	sub, _, _ := strings.Cut(up.Header.Get("Sec-WebSocket-Protocol"), ",")
	sess := decode.NewWSSession(wp.Protocol, strings.TrimSpace(sub), up, h)
	if sess == nil {
		return nil, fmt.Errorf("%s messages are not read by Opfence", wp.Protocol)
	}
	if len(s.Messages) == 0 {
		return nil, fmt.Errorf("socket fixture has no messages")
	}
	var out []SocketStep
	for _, m := range s.Messages {
		st := SocketStep{Step: sess.Client(m)}
		if st.Step.Decides() {
			st.Result = eng.EvaluateStep(up, st.Step)
		}
		sess.Forwarded(st.Step)
		out = append(out, st)
	}
	return out, nil
}

// IsSocket reports whether a fixture is a socket fixture: it has a message
// line.
func IsSocket(data []byte) bool {
	_, _, found := cutMessages(data)
	return found
}
