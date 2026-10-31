package cli

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/rakeshnitb23/opfence/internal/ca"
)

// TestHelperKubeChild is kubectl's part in TestRunWeakKube: it reads the
// session's kubeconfig and sends two requests to its server through the
// proxy, trusting only the kubeconfig's CA.
func TestHelperKubeChild(t *testing.T) {
	out := os.Getenv("OPFENCE_KUBE_HELPER_OUT")
	if out == "" {
		return
	}
	cfg, err := os.ReadFile(os.Getenv("KUBECONFIG"))
	if err != nil {
		os.Exit(90)
	}
	server := regexp.MustCompile(`server: (\S+)`).FindSubmatch(cfg)
	caData := regexp.MustCompile(`certificate-authority-data: (\S+)`).FindSubmatch(cfg)
	pemData, _ := base64.StdEncoding.DecodeString(string(caData[1]))
	pool := x509.NewCertPool()
	pool.AppendCertsFromPEM(pemData)
	proxy, _ := url.Parse(os.Getenv("HTTPS_PROXY"))
	c := &http.Client{Timeout: 10 * time.Second, Transport: &http.Transport{Proxy: http.ProxyURL(proxy), TLSClientConfig: &tls.Config{RootCAs: pool}}}
	got := map[string]string{"server": string(server[1]), "cbor": os.Getenv("KUBE_FEATURE_ClientsAllowCBOR")}
	for _, p := range []string{"/api/v1/namespaces/shop/pods", "/api/v1/secrets"} {
		resp, err := c.Get(string(server[1]) + p)
		if err != nil {
			got[p] = err.Error()
			continue
		}
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		got[p] = fmt.Sprintf("%d %s", resp.StatusCode, body)
	}
	data, _ := json.Marshal(got)
	if os.WriteFile(out, data, 0o600) != nil {
		os.Exit(91)
	}
	os.Exit(0)
}

// opfence run gives the program a kubeconfig whose loopback cluster goes
// through the proxy, which reaches the real server with its own CA and
// decides each request by the Kubernetes rules.
func TestRunWeakKube(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix sockets and signals")
	}
	isolate(t)
	clusterCA, err := ca.NewSession(nil, []net.IP{net.ParseIP("127.0.0.1")})
	if err != nil {
		t.Fatal(err)
	}
	leaf, err := clusterCA.Leaf("127.0.0.1")
	if err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	var seen []string
	api := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		seen = append(seen, r.Method+" "+r.URL.Path+" "+r.Host)
		mu.Unlock()
		fmt.Fprint(w, `{"kind":"PodList"}`)
	}))
	api.TLS = &tls.Config{Certificates: []tls.Certificate{*leaf}}
	api.StartTLS()
	defer api.Close()
	kubeconfig := filepath.Join(t.TempDir(), "config")
	if err := os.WriteFile(kubeconfig, []byte(fmt.Sprintf("apiVersion: v1\nkind: Config\nclusters:\n- name: kind\n  cluster:\n"+
		"    server: %s\n    certificate-authority-data: %s\ncontexts:\n- name: kind\n  context: {cluster: kind}\ncurrent-context: kind\n",
		api.URL, base64.StdEncoding.EncodeToString(clusterCA.CertPEM()))), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("KUBECONFIG", kubeconfig)
	out := filepath.Join(t.TempDir(), "child.json")
	t.Setenv("OPFENCE_KUBE_HELPER_OUT", out)
	code, _, errOut := run(t, "run", "--weak", "--", os.Args[0], "-test.run=^TestHelperKubeChild$")
	if code != 0 {
		t.Fatalf("exit %d\n%s", code, errOut)
	}
	port := strings.TrimPrefix(api.URL, "https://127.0.0.1:")
	if !strings.Contains(errOut, "Kubernetes: kubectl reaches 1 Kubernetes API server(s) through Opfence: 127.0.0.1:"+port) {
		t.Errorf("banner:\n%s", errOut)
	}
	data, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]string
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatal(err)
	}
	if got["server"] != "https://127-0-0-1.kube.opfence.invalid:"+port || got["cbor"] != "false" {
		t.Errorf("the session kubeconfig: %v", got)
	}
	if got["/api/v1/namespaces/shop/pods"] != `200 {"kind":"PodList"}` {
		t.Errorf("listing pods: %s", got["/api/v1/namespaces/shop/pods"])
	}
	if s := got["/api/v1/secrets"]; !strings.HasPrefix(s, "403 ") || !strings.Contains(s, "kubernetes.core.secrets.list-all-namespaces") {
		t.Errorf("listing Secrets: %s", s)
	}
	mu.Lock()
	defer mu.Unlock()
	if len(seen) != 1 || seen[0] != "GET /api/v1/namespaces/shop/pods 127.0.0.1:"+port {
		t.Errorf("the API server saw %v", seen)
	}
}
