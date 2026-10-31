package proxy

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/rakeshnitb23/opfence/internal/audit"
	"github.com/rakeshnitb23/opfence/internal/engine"
	"github.com/rakeshnitb23/opfence/internal/inject"
	"github.com/rakeshnitb23/opfence/internal/request"
)

// KubeEndpoint is a Kubernetes API server of the user's kubeconfig (stage
// 31c). The proxy intercepts it on its own port with the session's
// Kubernetes CA, which the session's kubeconfig trusts, and checks the
// server with its own CA.
type KubeEndpoint struct {
	Host, Port string
	// ServerName is the name the server's certificate is checked against,
	// and the one a client may send as its TLS server name: the
	// kubeconfig's tls-server-name, or Host.
	ServerName string
	// Alias is the name the session's kubeconfig gives a server on a
	// loopback address, so clients send it through the proxy.
	Alias string
	// RootCAs is the cluster's own CA; nil means the system's roots.
	RootCAs *x509.CertPool
	// Insecure skips checking the server's certificate, as the kubeconfig
	// says (insecure-skip-tls-verify).
	Insecure bool
	// ClientCerts are the client certificates the kubeconfig pairs with the
	// cluster. A client that presents one to the proxy has it presented to
	// the cluster.
	ClientCerts []tls.Certificate

	mu         sync.Mutex
	transports map[int]*http.Transport // by client certificate, -1 for none
}

// addr is the endpoint's host and port, the port left out when it is 443,
// as a Host header writes it.
func (ep *KubeEndpoint) addr() string {
	if ep.Port == "443" {
		return ep.Host
	}
	return net.JoinHostPort(ep.Host, ep.Port)
}

// kubeEndpoint returns the session's endpoint at host and port.
func (s *Server) kubeEndpoint(host, port string) *KubeEndpoint {
	for _, ep := range s.cfg.Kube {
		if (ep.Host == host || (ep.Alias != "" && ep.Alias == host)) && ep.Port == port {
			return ep
		}
	}
	return nil
}

// kubeConnKey carries an intercepted Kubernetes connection's endpoint
// from ConnContext to the handler.
type kubeConnKey struct{}

// interceptKube terminates TLS for a Kubernetes endpoint with a leaf from
// the session's Kubernetes CA, asking the client for its certificate, and
// hands the connection to the inner server.
func (s *Server) interceptKube(c net.Conn, ep *KubeEndpoint, name string) {
	done := make(chan struct{})
	tc := tls.Server(&closeNotifyConn{Conn: c, done: done}, &tls.Config{
		MinVersion: tls.VersionTLS12,
		NextProtos: []string{"h2", "http/1.1"},
		// The client's certificate chooses which of the kubeconfig's
		// identities the cluster sees; it is not checked here.
		ClientAuth: tls.RequestClientCert,
		GetCertificate: func(*tls.ClientHelloInfo) (*tls.Certificate, error) {
			return s.cfg.KubeCA.Leaf(name)
		},
	})
	s.kubeConns.Store(tc, ep)
	s.conns.push(tc)
	<-done
	s.kubeConns.Delete(tc)
}

// kubeConnContext tells the inner server's handler which endpoint and
// client certificate a connection is for.
func (s *Server) kubeConnContext(ctx context.Context, c net.Conn) context.Context {
	tc, ok := c.(*tls.Conn)
	if !ok {
		return ctx
	}
	v, ok := s.kubeConns.Load(tc)
	if !ok {
		return ctx
	}
	return context.WithValue(ctx, kubeConnKey{}, v.(*KubeEndpoint))
}

// kubeFrom returns the request's endpoint and the index of the client
// certificate its connection presented, or -1.
func kubeFrom(r *http.Request) (*KubeEndpoint, int) {
	ep, _ := r.Context().Value(kubeConnKey{}).(*KubeEndpoint)
	if ep == nil {
		return nil, -1
	}
	if r.TLS != nil && len(r.TLS.PeerCertificates) > 0 {
		presented := r.TLS.PeerCertificates[0].Raw
		for i, c := range ep.ClientCerts {
			if bytes.Equal(c.Certificate[0], presented) {
				return ep, i
			}
		}
	}
	return ep, -1
}

// kubeTLS is the TLS configuration for reaching ep, with client
// certificate cert (-1 for none).
func (s *Server) kubeTLS(ep *KubeEndpoint, cert int, protos []string) *tls.Config {
	cfg := &tls.Config{ServerName: ep.ServerName, RootCAs: ep.RootCAs, MinVersion: tls.VersionTLS12, NextProtos: protos}
	if cfg.RootCAs == nil {
		cfg.RootCAs = s.cfg.UpstreamRootCAs
	}
	if ep.Insecure {
		cfg.InsecureSkipVerify = true
	}
	if cert >= 0 {
		cfg.Certificates = []tls.Certificate{ep.ClientCerts[cert]}
	}
	return cfg
}

// kubeTransport returns the transport for ep with client certificate cert:
// one per identity, so connections are never shared between them.
func (s *Server) kubeTransport(ep *KubeEndpoint, cert int) *http.Transport {
	ep.mu.Lock()
	defer ep.mu.Unlock()
	if t, ok := ep.transports[cert]; ok {
		return t
	}
	if ep.transports == nil {
		ep.transports = map[int]*http.Transport{}
	}
	t := &http.Transport{
		DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
			// The kubeconfig names this server, private address or not.
			return s.dial(ctx, network, net.JoinHostPort(ep.Host, ep.Port), true)
		},
		TLSClientConfig:       s.kubeTLS(ep, cert, nil),
		ForceAttemptHTTP2:     true,
		MaxIdleConns:          20,
		IdleConnTimeout:       90 * time.Second,
		TLSHandshakeTimeout:   15 * time.Second,
		ExpectContinueTimeout: time.Second,
	}
	ep.transports[cert] = t
	return t
}

// kubeRoundTripper sends a forwarded request through its Kubernetes
// endpoint's transport, and every other one through the default.
type kubeRoundTripper struct{ s *Server }

func (k kubeRoundTripper) RoundTrip(r *http.Request) (*http.Response, error) {
	if f, ok := r.Context().Value(fwdKey{}).(*fwd); ok && f.kube != nil {
		return k.s.kubeTransport(f.kube, f.kubeCert).RoundTrip(r)
	}
	return k.s.transport.RoundTrip(r)
}

// isStreamUpgrade reports whether r asks to open a stream the provider
// takes unread (stream_upgrades): a WebSocket upgrade, or an SPDY one as
// kubectl falls back to.
func isStreamUpgrade(r *http.Request) bool {
	if r.ProtoMajor != 1 || !headerHasToken(r.Header, "Connection", "upgrade") {
		return false
	}
	for _, v := range r.Header.Values("Upgrade") {
		for _, t := range strings.Split(v, ",") {
			t = strings.ToLower(strings.TrimSpace(t))
			if t == "websocket" || strings.HasPrefix(t, "spdy/") {
				return true
			}
		}
	}
	return false
}

// serveStream relays an allowed stream upgrade to a Kubernetes endpoint
// (exec, attach, port forwarding): the upgrade goes out as decided, and
// once the cluster switches protocols the two connections are spliced
// without being read. The decision on opening the stream covers it.
func (s *Server) serveStream(w http.ResponseWriter, r *http.Request, req *request.Request, res *engine.Result, entry audit.Entry, ep *KubeEndpoint, cert int) {
	fail := func(status int, msg string) {
		entry.Outcome, entry.Status, entry.Reason = "error", status, msg
		s.record(entry)
		http.Error(w, msg, status)
	}
	if r.ContentLength != 0 || len(r.TransferEncoding) > 0 {
		s.block(w, req, res, entry, http.StatusForbidden, "Opfence blocks stream upgrades that carry a body.")
		return
	}
	out := r.Header.Clone()
	rawQuery, inj := inject.Request(res.Provider, out, r.URL.RawQuery, s.cfg.Secrets)
	entry.Credentials = inj.Injected
	for _, k := range []string{"Proxy-Connection", "Proxy-Authorization", "Keep-Alive", "Te", "Trailer", "Transfer-Encoding", "Content-Length", "Host"} {
		out.Del(k)
	}
	target := req.Path
	if rawQuery != "" {
		target += "?" + rawQuery
	}
	var head bytes.Buffer
	fmt.Fprintf(&head, "%s %s HTTP/1.1\r\nHost: %s\r\n", r.Method, target, ep.addr())
	if out.Get("User-Agent") == "" {
		out["User-Agent"] = []string{""}
	}
	_ = out.Write(&head)
	head.WriteString("\r\n")

	ctx, cancel := context.WithTimeout(r.Context(), wsHandshakeTimeout)
	raw, err := s.dial(ctx, "tcp", net.JoinHostPort(ep.Host, ep.Port), true)
	if err != nil {
		cancel()
		fail(http.StatusBadGateway, "Opfence could not reach the API server: "+err.Error())
		return
	}
	up := tls.Client(raw, s.kubeTLS(ep, cert, []string{"http/1.1"}))
	err = up.HandshakeContext(ctx)
	cancel()
	if err != nil {
		_ = raw.Close()
		fail(http.StatusBadGateway, "Opfence could not reach the API server: "+err.Error())
		return
	}
	_ = up.SetDeadline(time.Now().Add(wsHandshakeTimeout))
	upR := bufio.NewReader(up)
	var resp *http.Response
	if _, err = up.Write(head.Bytes()); err == nil {
		resp, err = http.ReadResponse(upR, &http.Request{Method: r.Method})
	}
	if err != nil {
		_ = up.Close()
		fail(http.StatusBadGateway, "Opfence could not upgrade the connection to the API server: "+err.Error())
		return
	}
	_ = up.SetDeadline(time.Time{})
	s.scrubber.Header(resp.Header)
	if resp.StatusCode != http.StatusSwitchingProtocols {
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
		entry.Status = resp.StatusCode
		s.record(entry)
		refusedUpgrade(r.Context(), w, up, resp.StatusCode, body)
		return
	}
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
	// What the client sent past the upgrade, and what the server sent past
	// its answer, go first.
	client := &prefixConn{Conn: cc, r: io.MultiReader(cbuf.Reader, cc)}
	server := &prefixConn{Conn: up, r: io.MultiReader(upR, up)}
	splice(client, server)
}
