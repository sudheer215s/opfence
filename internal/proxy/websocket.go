package proxy

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/rakeshnitb23/opfence/internal/audit"
	"github.com/rakeshnitb23/opfence/internal/catalog"
	"github.com/rakeshnitb23/opfence/internal/decode"
	"github.com/rakeshnitb23/opfence/internal/engine"
	"github.com/rakeshnitb23/opfence/internal/inject"
	"github.com/rakeshnitb23/opfence/internal/request"
	"github.com/rakeshnitb23/opfence/internal/websocket"
)

// maxWSMessage bounds one data message on a relayed socket. Larger ones
// close the socket (1009), so memory per connection is bounded. A variable
// for tests.
var maxWSMessage = 16 << 20

const (
	// wsHandshakeTimeout bounds dialling the API and its answer to the
	// upgrade.
	wsHandshakeTimeout = 30 * time.Second
	// wsCloseWait is how long a relay waits, once one side has closed, for
	// the other side's close frame.
	wsCloseWait = 5 * time.Second
)

// upgradeRefused says why an upgrade request cannot be relayed, or returns
// "" when it can: a WebSocket upgrade over HTTP/1.1, to one of its
// provider's websocket paths, whose protocol Opfence reads.
func (s *Server) upgradeRefused(r *http.Request, req *request.Request) string {
	const generic = "Opfence blocks protocol upgrades on API hosts unless it reads what they carry: only WebSocket upgrades to the paths a provider lists are relayed."
	if !decode.IsWebSocketUpgrade(r.Method, r.Header) || r.ProtoMajor != 1 || !headerHasToken(r.Header, "Connection", "upgrade") {
		return generic
	}
	p := s.cfg.Engine.Catalog.ProviderForHost(req.Host)
	if p == nil {
		return generic
	}
	wp, ok := decode.WebSocketPathFor(req.Path, p.Hints(req.Host).WebSocket)
	switch {
	case !ok:
		return fmt.Sprintf("Opfence does not read WebSocket messages on %s for %s, so it blocks the upgrade.", req.Path, p.Title)
	case decode.NewWSSession(wp.Protocol, "", req, decode.Hints{}) == nil:
		return fmt.Sprintf("Opfence does not read %s messages, so it blocks the upgrade.", wp.Protocol)
	case r.Header.Get("Sec-WebSocket-Version") != "13" || r.Header.Get("Sec-WebSocket-Key") == "":
		return "Opfence relays WebSocket version 13 upgrades with a Sec-WebSocket-Key only."
	case len(r.Header.Values("Sec-WebSocket-Protocol")) > 0 && len(decode.WebSocketSubprotocols[wp.Protocol]) > 0 &&
		len(decode.ReadableSubprotocols(wp.Protocol, r.Header.Values("Sec-WebSocket-Protocol"))) == 0:
		return fmt.Sprintf("Opfence does not read the WebSocket subprotocols offered (%s); it reads %s.",
			strings.Join(r.Header.Values("Sec-WebSocket-Protocol"), ", "), strings.Join(decode.WebSocketSubprotocols[wp.Protocol], ", "))
	case r.ContentLength != 0 || len(r.TransferEncoding) > 0:
		// What follows the upgrade is read as frames; a body would be too.
		return "Opfence blocks WebSocket upgrades that carry a body."
	}
	return ""
}

// webSocketPath returns the websocket path an allowed upgrade opens.
func (s *Server) webSocketPath(p *catalog.Provider, r *http.Request, req *request.Request) (decode.WebSocketPath, bool) {
	if p == nil || !decode.IsWebSocketUpgrade(r.Method, r.Header) {
		return decode.WebSocketPath{}, false
	}
	return decode.WebSocketPathFor(req.Path, p.Hints(req.Host).WebSocket)
}

// serveWebSocket relays an allowed WebSocket upgrade (docs/ARCHITECTURE.md
// §8.8). Opfence dials the API itself, sends the upgrade as decided (its
// placeholders swapped, no extensions offered), checks the answer, and then
// relays the socket message by message, deciding each one the agent sends.
func (s *Server) serveWebSocket(w http.ResponseWriter, r *http.Request, req *request.Request, res *engine.Result, entry audit.Entry, wp decode.WebSocketPath) {
	host, prov := req.Host, res.Provider
	if p, err := url.PathUnescape(req.Path); err != nil || (&url.URL{Path: p, RawPath: req.Path}).EscapedPath() != req.Path {
		s.block(w, req, res, entry, http.StatusBadRequest, "Opfence could not forward this path unchanged, so it blocks it.")
		return
	}
	// The session reads the upgrade as decided, without real secrets.
	handshake := *req
	handshake.Header = req.Header.Clone()

	out := r.Header.Clone()
	rawQuery, inj := inject.Request(prov, out, r.URL.RawQuery, s.cfg.Secrets)
	entry.Credentials = inj.Injected
	if len(inj.Foreign) > 0 {
		entry.Reason = fmt.Sprintf("placeholder for %s sent to %s; not swapped in", strings.Join(inj.Foreign, ", "), host)
	}
	for _, k := range []string{"Connection", "Upgrade", "Sec-Websocket-Extensions", "Proxy-Connection", "Proxy-Authorization",
		"Keep-Alive", "Te", "Trailer", "Transfer-Encoding", "Content-Length", "Host"} {
		out.Del(k)
	}
	out.Set("Connection", "Upgrade")
	out.Set("Upgrade", "websocket")
	// Only subprotocols whose messages Opfence reads are offered.
	subs := decode.ReadableSubprotocols(wp.Protocol, r.Header.Values("Sec-WebSocket-Protocol"))
	out.Del("Sec-Websocket-Protocol")
	if len(subs) > 0 {
		out.Set("Sec-WebSocket-Protocol", strings.Join(subs, ", "))
	}
	target := req.Path
	if rawQuery != "" {
		target += "?" + rawQuery
	}
	var head bytes.Buffer
	fmt.Fprintf(&head, "GET %s HTTP/1.1\r\nHost: %s\r\n", target, host)
	if out.Get("User-Agent") == "" {
		out["User-Agent"] = []string{""} // Header.Write skips it; no Go default either
	}
	_ = out.Write(&head)
	head.WriteString("\r\n")

	fail := func(status int, msg string) {
		entry.Outcome, entry.Status, entry.Reason = "error", status, msg
		s.record(entry)
		http.Error(w, msg, status)
	}
	ctx, cancel := context.WithTimeout(r.Context(), wsHandshakeTimeout)
	up, err := s.dialTLS(ctx, host)
	cancel()
	if err != nil {
		fail(http.StatusBadGateway, "Opfence could not reach the API: "+err.Error())
		return
	}
	_ = up.SetDeadline(time.Now().Add(wsHandshakeTimeout))
	upR := bufio.NewReader(up)
	var resp *http.Response
	if _, err = up.Write(head.Bytes()); err == nil {
		resp, err = http.ReadResponse(upR, &http.Request{Method: http.MethodGet})
	}
	if err != nil {
		_ = up.Close()
		fail(http.StatusBadGateway, "Opfence could not upgrade the connection to the API: "+err.Error())
		return
	}
	_ = up.SetDeadline(time.Time{})
	s.scrubber.Header(resp.Header)

	if resp.StatusCode != http.StatusSwitchingProtocols {
		// The API refused the upgrade: its answer goes back, scrubbed.
		defer up.Close()
		defer resp.Body.Close()
		for k, vs := range resp.Header {
			if !hopByHop(k) {
				w.Header()[k] = vs
			}
		}
		var body io.Reader = resp.Body
		if s.scrubber.Active() {
			body = s.scrubber.Reader(resp.Body, nil)
		}
		w.WriteHeader(resp.StatusCode)
		_, _ = io.Copy(w, io.LimitReader(body, 1<<20))
		entry.Status = resp.StatusCode
		s.record(entry)
		return
	}
	sub := resp.Header.Get("Sec-WebSocket-Protocol")
	why := ""
	switch {
	case !headerHasToken(resp.Header, "Upgrade", "websocket") || !headerHasToken(resp.Header, "Connection", "upgrade") ||
		resp.Header.Get("Sec-WebSocket-Accept") != websocket.AcceptKey(r.Header.Get("Sec-WebSocket-Key")):
		why = "the API's answer to the upgrade is not a WebSocket handshake"
	case resp.Header.Get("Sec-WebSocket-Extensions") != "":
		// Compressed frames could not be read.
		why = "the API turned on a WebSocket extension Opfence did not offer and cannot read (" + resp.Header.Get("Sec-WebSocket-Extensions") + ")"
	case sub != "" && !slices.Contains(subs, sub):
		why = "the API chose a WebSocket subprotocol Opfence did not offer"
	}
	if why != "" {
		_ = up.Close()
		fail(http.StatusBadGateway, "Opfence refused the API's answer: "+why)
		return
	}
	sess := decode.NewWSSession(wp.Protocol, sub, &handshake, prov.Hints(host))

	cc, cbuf, err := http.NewResponseController(w).Hijack()
	if err != nil {
		_ = up.Close()
		fail(http.StatusInternalServerError, "Opfence could not take over the connection: "+err.Error())
		return
	}
	defer cc.Close()
	defer up.Close()
	_ = cc.SetDeadline(time.Time{})
	var ans bytes.Buffer
	ans.WriteString("HTTP/1.1 101 Switching Protocols\r\n")
	_ = resp.Header.Write(&ans)
	ans.WriteString("\r\n")
	if _, err := cc.Write(ans.Bytes()); err != nil {
		return
	}
	entry.Status = http.StatusSwitchingProtocols
	s.record(entry)

	x := &wsRelay{
		s: s, host: host, path: wp.Path, prov: prov, handshake: &handshake, sess: sess,
		fromClient: websocket.NewReader(cbuf.Reader, true, maxWSMessage),
		toClient:   websocket.NewWriter(cc, false),
		fromServer: websocket.NewReader(upR, false, maxWSMessage),
		toServer:   websocket.NewWriter(up, true),
	}
	x.ctx, x.cancel = context.WithCancel(r.Context())
	x.run(cc, up)
}

// dialTLS opens a TLS connection to host's API for HTTP/1.1.
func (s *Server) dialTLS(ctx context.Context, host string) (net.Conn, error) {
	raw, err := s.dial(ctx, "tcp", net.JoinHostPort(host, "443"), false)
	if err != nil {
		return nil, err
	}
	tc := tls.Client(raw, &tls.Config{ServerName: host, RootCAs: s.cfg.UpstreamRootCAs, MinVersion: tls.VersionTLS12, NextProtos: []string{"http/1.1"}})
	if err := tc.HandshakeContext(ctx); err != nil {
		_ = raw.Close()
		return nil, err
	}
	return tc, nil
}

// headerHasToken reports whether a comma-separated header names tok, in
// any case.
func headerHasToken(h http.Header, name, tok string) bool {
	for _, v := range h.Values(name) {
		for _, t := range strings.Split(v, ",") {
			if strings.EqualFold(strings.TrimSpace(t), tok) {
				return true
			}
		}
	}
	return false
}

func hopByHop(k string) bool {
	switch http.CanonicalHeaderKey(k) {
	case "Connection", "Upgrade", "Keep-Alive", "Transfer-Encoding", "Te", "Trailer", "Proxy-Connection", "Content-Length":
		return true
	}
	return false
}

// wsRelay relays one socket. The client side's messages are decided one at
// a time; the API's pass as they come, scrubbed.
type wsRelay struct {
	s          *Server
	ctx        context.Context
	cancel     context.CancelFunc
	host, path string
	prov       *catalog.Provider
	handshake  *request.Request
	sess       decode.WSSession

	fromClient *websocket.Reader
	toClient   *websocket.Writer
	fromServer *websocket.Reader
	toServer   *websocket.Writer
}

// run relays until both sides have closed, or one has and the other has
// not answered within wsCloseWait.
func (x *wsRelay) run(cc, up net.Conn) {
	done := make(chan struct{}, 2)
	go func() { x.clientToServer(); done <- struct{}{} }()
	go func() { x.serverToClient(); done <- struct{}{} }()
	<-done
	select {
	case <-done:
	case <-time.After(wsCloseWait):
		x.cancel() // an approval still waiting ends too
		_ = cc.Close()
		_ = up.Close()
		<-done
	}
	x.cancel()
}

// clientToServer reads the agent's messages, decides each, and forwards
// what is allowed.
func (x *wsRelay) clientToServer() {
	for {
		m, err := x.fromClient.Next()
		if err != nil {
			x.readFailed(err, x.toClient, x.toServer)
			return
		}
		switch m.Op {
		case websocket.OpPing, websocket.OpPong:
			if x.toServer.Write(m) != nil {
				return
			}
			continue
		case websocket.OpClose:
			_ = x.toServer.Write(m)
			return
		}
		step := x.sess.Client(decode.WSMessage{Binary: m.Op == websocket.OpBinary, Data: m.Data})
		if step.Decides() {
			forward, open := x.decide(step)
			if !open {
				return
			}
			if !forward {
				continue
			}
		}
		if !x.forward(step) {
			return
		}
	}
}

// decide decides one step: whether it goes to the API, and whether the
// socket stays open. A step blocked on an open socket has been answered in
// the protocol.
func (x *wsRelay) decide(step decode.WSStep) (forward, open bool) {
	res := x.s.cfg.Engine.EvaluateStep(x.handshake, step)
	entry := audit.Entry{Event: "message", Host: x.host, Path: auditPath(x.path), Method: step.Kind}
	ok, why := x.s.decide(x.ctx, &res, Pending{Method: "WebSocket " + step.Kind, Host: x.host, Path: x.path}, &entry)
	if ok {
		x.s.record(entry)
		return true, true
	}
	entry.Outcome, entry.Reason = "blocked", why
	x.s.record(entry)
	msg := blockText(&res, why)
	replies, closeSocket := x.sess.Blocked(step, msg)
	for _, rm := range replies {
		if x.toClient.Write(wsFrame(rm)) != nil {
			return false, false
		}
	}
	if closeSocket {
		_ = x.toClient.Write(websocket.CloseMessage(websocket.ClosePolicyViolation, msg))
		_ = x.toServer.Write(websocket.CloseMessage(websocket.CloseGoingAway, ""))
		return false, false
	}
	return false, true
}

func (x *wsRelay) forward(step decode.WSStep) bool {
	for _, fm := range step.Forward {
		if len(step.Swap) > 0 {
			// The connection's credential, where the protocol carries it.
			if data, _ := inject.Message(x.prov, fm.Data, step.Swap, x.s.cfg.Secrets); data != nil {
				fm.Data = data
			}
		}
		if x.toServer.Write(wsFrame(fm)) != nil {
			return false
		}
	}
	x.sess.Forwarded(step)
	return true
}

// serverToClient passes the API's messages on, scrubbed.
func (x *wsRelay) serverToClient() {
	scrub := func(b []byte) []byte {
		if x.s.scrubber.Active() {
			return x.s.scrubber.Bytes(b)
		}
		return b
	}
	for {
		m, err := x.fromServer.Next()
		if err != nil {
			x.readFailed(err, x.toServer, x.toClient)
			return
		}
		if m.IsControl() {
			m.Data = scrub(m.Data)
			if x.toClient.Write(m) != nil || m.Op == websocket.OpClose {
				return
			}
			continue
		}
		for _, out := range x.sess.Server(decode.WSMessage{Binary: m.Op == websocket.OpBinary, Data: m.Data}) {
			out.Data = scrub(out.Data)
			if x.toClient.Write(wsFrame(out)) != nil {
				return
			}
		}
	}
}

// readFailed ends a relay whose reader failed: a frame the protocol does
// not allow or a message too large is answered with a close frame to the
// side that sent it, and the other side is told the relay is going away.
func (x *wsRelay) readFailed(err error, sender, other *websocket.Writer) {
	var pe websocket.ProtocolError
	switch {
	case errors.Is(err, websocket.ErrTooBig):
		_ = sender.Write(websocket.CloseMessage(websocket.CloseTooBig, fmt.Sprintf("Opfence relays messages of up to %d MiB", maxWSMessage>>20)))
	case errors.As(err, &pe):
		_ = sender.Write(websocket.CloseMessage(websocket.CloseProtocolError, pe.Error()))
	default:
		return // the connection itself ended
	}
	_ = other.Write(websocket.CloseMessage(websocket.CloseGoingAway, ""))
}

func wsFrame(m decode.WSMessage) websocket.Message {
	if m.Binary {
		return websocket.Message{Op: websocket.OpBinary, Data: m.Data}
	}
	return websocket.Message{Op: websocket.OpText, Data: m.Data}
}
