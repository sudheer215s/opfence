package proxy

import (
	"bufio"

	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/rakeshnitb23/opfence/internal/ca"
	"github.com/rakeshnitb23/opfence/internal/catalog"
	"github.com/rakeshnitb23/opfence/internal/engine"
	"github.com/rakeshnitb23/opfence/internal/policy"
)

const kubeAlias = "127-0-0-1.kube.opfence.invalid"

// kubeEnv is a proxy with one Kubernetes endpoint: a fake API server on a
// loopback port, with its own CA, that asks for client certificates and
// answers upgrades by echoing.
type kubeEnv struct {
	t        *testing.T
	srv      *Server
	httpAddr string
	port     string
	kubeCA   *ca.CA
	client   tls.Certificate

	mu   sync.Mutex
	seen []string // "METHOD path host cert-CN"
}

func selfSignedClient(t *testing.T, cn string) tls.Certificate {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: cn, Organization: []string{"system:masters"}},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth}}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, key.Public(), key)
	if err != nil {
		t.Fatal(err)
	}
	return tls.Certificate{Certificate: [][]byte{der}, PrivateKey: key}
}

func newKubeEnv(t *testing.T, approver Approver) *kubeEnv {
	t.Helper()
	k := &kubeEnv{t: t, client: selfSignedClient(t, "agent")}
	clusterCA, err := ca.NewSession(nil, []net.IP{net.ParseIP("127.0.0.1")})
	if err != nil {
		t.Fatal(err)
	}
	api := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		cn := "-"
		if len(r.TLS.PeerCertificates) > 0 {
			cn = r.TLS.PeerCertificates[0].Subject.CommonName
		}
		k.mu.Lock()
		k.seen = append(k.seen, fmt.Sprintf("%s %s %s %s", r.Method, r.URL.RequestURI(), r.Host, cn))
		k.mu.Unlock()
		if r.Header.Get("Upgrade") != "" {
			if r.URL.Query().Get("refuse") != "" {
				w.WriteHeader(http.StatusBadRequest) // no length: ends when the server closes
				_ = http.NewResponseController(w).Flush()
				<-r.Context().Done()
				return
			}
			c, rw, err := http.NewResponseController(w).Hijack()
			if err != nil {
				return
			}
			defer c.Close()
			fmt.Fprintf(rw, "HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: %s\r\n\r\n", r.Header.Get("Upgrade"))
			_ = rw.Flush()
			_, _ = io.Copy(c, rw) // echo
			return
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"kind":"PodList","items":[]}`)
	}))
	leaf, err := clusterCA.Leaf("127.0.0.1")
	if err != nil {
		t.Fatal(err)
	}
	// Go clients send no server name for an address, so the certificate is
	// the only one.
	api.TLS = &tls.Config{ClientAuth: tls.RequestClientCert, Certificates: []tls.Certificate{*leaf}}
	api.StartTLS()
	t.Cleanup(api.Close)
	_, k.port, _ = net.SplitHostPort(api.Listener.Addr().String())

	cat, err := catalog.Embedded()
	if err != nil {
		t.Fatal(err)
	}
	eng := engine.New(cat, policy.Resolve(nil, nil))
	eng.Hosts = map[string]*catalog.Provider{"127.0.0.1": cat.Provider("kubernetes")}
	main, err := ca.New("test", []string{"api.github.com"})
	if err != nil {
		t.Fatal(err)
	}
	if k.kubeCA, err = ca.NewSession([]string{kubeAlias}, []net.IP{net.ParseIP("127.0.0.1")}); err != nil {
		t.Fatal(err)
	}
	if approver == nil {
		approver = NoApprover{}
	}
	srv, err := New(Config{Engine: eng, CA: main, KubeCA: k.kubeCA, Session: "test", Mode: "strict", Approver: approver, Logf: t.Logf,
		Kube: []*KubeEndpoint{{Host: "127.0.0.1", Port: k.port, ServerName: "127.0.0.1", Alias: kubeAlias,
			RootCAs: clusterCA.Pool(), ClientCerts: []tls.Certificate{k.client}}}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { srv.Close() })
	k.srv = srv
	hl, _ := net.Listen("tcp", "127.0.0.1:0")
	k.httpAddr = hl.Addr().String()
	go srv.ServeHTTPProxy(hl)
	return k
}

// httpClient is kubectl through the proxy: it trusts the session CA and
// presents cert, if any.
func (k *kubeEnv) httpClient(cert *tls.Certificate) *http.Client {
	cfg := &tls.Config{RootCAs: k.kubeCA.Pool()}
	if cert != nil {
		cfg.Certificates = []tls.Certificate{*cert}
	}
	tr := &http.Transport{Proxy: http.ProxyURL(&url.URL{Scheme: "http", Host: k.httpAddr}), TLSClientConfig: cfg, ForceAttemptHTTP2: true}
	k.t.Cleanup(tr.CloseIdleConnections)
	return &http.Client{Transport: tr, Timeout: 10 * time.Second}
}

func (k *kubeEnv) lastSeen() string {
	k.mu.Lock()
	defer k.mu.Unlock()
	if len(k.seen) == 0 {
		return ""
	}
	return k.seen[len(k.seen)-1]
}

func TestKubeEndpoints(t *testing.T) {
	k := newKubeEnv(t, nil)
	base := "https://" + kubeAlias + ":" + k.port

	// A read reaches the cluster with the client's certificate, by its own
	// address, through HTTP/2.
	resp, err := k.httpClient(&k.client).Get(base + "/api/v1/namespaces/shop/pods")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 200 || resp.ProtoMajor != 2 || k.lastSeen() != "GET /api/v1/namespaces/shop/pods 127.0.0.1:"+k.port+" agent" {
		t.Fatalf("read: %d %s, the server saw %q", resp.StatusCode, resp.Proto, k.lastSeen())
	}
	// Without a certificate, the cluster gets none; another one is not
	// passed on either.
	other := selfSignedClient(t, "intruder")
	for _, cert := range []*tls.Certificate{nil, &other} {
		resp, err := k.httpClient(cert).Get(base + "/api/v1/namespaces/shop/pods")
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		if !strings.HasSuffix(k.lastSeen(), " -") {
			t.Errorf("the server saw %q", k.lastSeen())
		}
	}
	// Decided by the Kubernetes rules: deleting a namespace needs a human.
	n := len(k.seen)
	req, _ := http.NewRequest(http.MethodDelete, base+"/api/v1/namespaces/shop", nil)
	resp, err = k.httpClient(&k.client).Do(req)
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != http.StatusForbidden || len(k.seen) != n || !strings.Contains(string(body), "kubernetes.core.namespaces.delete") {
		t.Fatalf("namespace deletion: %d %s", resp.StatusCode, body)
	}
	// The server's own address works too (kubectl with the kubeconfig's
	// server, not the alias), and HTTP/1.1.
	direct := k.httpClient(&k.client)
	direct.Transport.(*http.Transport).TLSNextProto = map[string]func(string, *tls.Conn) http.RoundTripper{}
	resp, err = direct.Get("https://127.0.0.1:" + k.port + "/api/v1/nodes")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 200 || !strings.HasPrefix(k.lastSeen(), "GET /api/v1/nodes ") {
		t.Fatalf("by address: %d, the server saw %q", resp.StatusCode, k.lastSeen())
	}
}

func TestKubeEndpointRefusals(t *testing.T) {
	k := newKubeEnv(t, nil)
	// A TLS server name other than the server's own.
	c, code := connect(t, k.httpAddr, kubeAlias+":"+k.port)
	if code != 200 {
		t.Fatalf("CONNECT: %d", code)
	}
	tc := tls.Client(c, &tls.Config{ServerName: "evil.example.com", RootCAs: k.kubeCA.Pool()})
	if err := tc.Handshake(); err == nil {
		t.Error("a handshake for another name succeeded")
	}
	c.Close()
	// Another port of the same loopback address is not the cluster.
	if c, code := connect(t, k.httpAddr, "127.0.0.1:1"); code != http.StatusForbidden {
		t.Errorf("another loopback port: %d", code)
	} else {
		c.Close()
	}
	// A Host header for another server on the connection.
	req, _ := http.NewRequest(http.MethodGet, "https://"+kubeAlias+":"+k.port+"/api", nil)
	req.Host = "api.github.com"
	resp, err := k.httpClient(nil).Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusMisdirectedRequest {
		t.Errorf("another Host: %d", resp.StatusCode)
	}
}

// upgrade opens an HTTP/1.1 connection through the proxy and sends an
// upgrade request.
func (k *kubeEnv) upgrade(method, path, proto string) (net.Conn, *bufio.Reader, *http.Response) {
	k.t.Helper()
	c, code := connect(k.t, k.httpAddr, kubeAlias+":"+k.port)
	if code != 200 {
		k.t.Fatalf("CONNECT: %d", code)
	}
	tc := tls.Client(c, &tls.Config{ServerName: kubeAlias, RootCAs: k.kubeCA.Pool(), Certificates: []tls.Certificate{k.client}, NextProtos: []string{"http/1.1"}})
	_ = tc.SetDeadline(time.Now().Add(10 * time.Second))
	fmt.Fprintf(tc, "%s %s HTTP/1.1\r\nHost: %s:%s\r\nConnection: Upgrade\r\nUpgrade: %s\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n",
		method, path, kubeAlias, k.port, proto)
	br := bufio.NewReader(tc)
	resp, err := http.ReadResponse(br, &http.Request{Method: method})
	if err != nil {
		k.t.Fatal(err)
	}
	return tc, br, resp
}

// Exec, attach and port forwarding are decided when they open, then relayed
// unread over WebSocket or SPDY.
func TestKubeStreams(t *testing.T) {
	a := &approveAll{}
	k := newKubeEnv(t, a)
	for _, c := range []struct{ method, path, proto string }{
		{"GET", "/api/v1/namespaces/shop/pods/web/exec?command=sh&stdin=true", "websocket"},
		{"POST", "/api/v1/namespaces/shop/pods/web/exec?command=sh&stdin=true", "SPDY/3.1"},
		{"POST", "/api/v1/namespaces/shop/pods/db/portforward?ports=5432", "SPDY/3.1"},
	} {
		calls := a.calls.Load()
		conn, br, resp := k.upgrade(c.method, c.path, c.proto)
		if resp.StatusCode != http.StatusSwitchingProtocols || a.calls.Load() != calls+1 {
			t.Fatalf("%s %s: %d, approvals %d", c.method, c.path, resp.StatusCode, a.calls.Load()-calls)
		}
		if !strings.HasPrefix(k.lastSeen(), c.method+" "+c.path+" 127.0.0.1:"+k.port+" agent") {
			t.Errorf("the server saw %q", k.lastSeen())
		}
		fmt.Fprint(conn, "ls -l\n")
		line, err := br.ReadString('\n')
		if err != nil || line != "ls -l\n" {
			t.Errorf("%s: echo %q %v", c.path, line, err)
		}
		conn.Close()
	}
	// The cluster's refusal comes back at once, even without a length.
	start := time.Now()
	conn, _, resp := k.upgrade("GET", "/api/v1/namespaces/shop/pods/web/exec?command=sh&refuse=1", "websocket")
	conn.Close()
	if resp.StatusCode != http.StatusBadRequest || time.Since(start) > 5*time.Second {
		t.Errorf("refused upgrade: %d after %s", resp.StatusCode, time.Since(start))
	}
	// A denied stream never reaches the cluster.
	denied := newKubeEnv(t, nil)
	conn, _, resp = denied.upgrade("POST", "/api/v1/namespaces/shop/pods/web/exec?command=sh", "SPDY/3.1")
	conn.Close()
	if resp.StatusCode != http.StatusForbidden || denied.lastSeen() != "" {
		t.Errorf("denied exec: %d, the server saw %q", resp.StatusCode, denied.lastSeen())
	}
	// An upgrade the rules read as a read (a WebSocket watch) needs no one.
	calls := a.calls.Load()
	conn, _, resp = k.upgrade("GET", "/api/v1/namespaces?watch=true", "websocket")
	conn.Close()
	if resp.StatusCode != http.StatusSwitchingProtocols || a.calls.Load() != calls {
		t.Errorf("watch: %d, approvals %d", resp.StatusCode, a.calls.Load()-calls)
	}
}
