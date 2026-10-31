package launch

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/pem"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"go.yaml.in/yaml/v3"

	"github.com/rakeshnitb23/opfence/internal/ca"
)

func writeClientCert(t *testing.T, dir string) (certPath, keyPath string) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "admin"},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth}}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, key.Public(), key)
	if err != nil {
		t.Fatal(err)
	}
	kd, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	certPath, keyPath = filepath.Join(dir, "admin.crt"), filepath.Join(dir, "admin.key")
	if err := os.WriteFile(certPath, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(keyPath, pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: kd}), 0o600); err != nil {
		t.Fatal(err)
	}
	return certPath, keyPath
}

func TestKubeConfig(t *testing.T) {
	home := t.TempDir()
	if k, err := KubeConfig(t.TempDir(), home, func(string) string { return "" }); k != nil || err != nil {
		t.Fatalf("no kubeconfig: %v %v", k, err)
	}

	dir := t.TempDir()
	writeClientCert(t, dir)
	clusterCA, err := ca.NewSession(nil, []net.IP{net.ParseIP("127.0.0.1")})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "cluster-ca.crt"), clusterCA.CertPEM(), 0o600); err != nil {
		t.Fatal(err)
	}
	first := filepath.Join(dir, "first.yaml")
	if err := os.WriteFile(first, []byte(`apiVersion: v1
kind: Config
clusters:
- name: kind
  cluster:
    server: https://127.0.0.1:6443
    certificate-authority: cluster-ca.crt
users:
- name: kind-admin
  user:
    client-certificate: admin.crt
    client-key: admin.key
contexts:
- name: kind
  context: {cluster: kind, user: kind-admin}
current-context: kind
preferences: {}
`), 0o600); err != nil {
		t.Fatal(err)
	}
	second := filepath.Join(dir, "second.yaml")
	if err := os.WriteFile(second, []byte(`apiVersion: v1
kind: Config
clusters:
- name: kind
  cluster: {server: https://ignored.example.com}
- name: prod
  cluster:
    server: https://Prod.Example.com
    tls-server-name: api.prod.internal
    insecure-skip-tls-verify: true
- name: legacy
  cluster: {server: http://10.0.0.5:8080}
- name: private
  cluster: {server: "https://[fd00::5]:6443", certificate-authority-data: CADATA}
users:
- name: prod-user
  user:
    token: real-token
    exec: {apiVersion: client.authentication.k8s.io/v1, command: ./bin/plugin}
contexts:
- name: prod
  context: {cluster: prod, user: prod-user, namespace: shop}
current-context: prod
`), 0o600); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(second)
	if err := os.WriteFile(second, []byte(strings.Replace(string(b), "CADATA", base64.StdEncoding.EncodeToString(clusterCA.CertPEM()), 1)), 0o600); err != nil {
		t.Fatal(err)
	}
	getenv := func(k string) string {
		if k == "KUBECONFIG" {
			return first + string(os.PathListSeparator) + second + string(os.PathListSeparator) + filepath.Join(dir, "missing.yaml")
		}
		return ""
	}
	out := t.TempDir()
	k, err := KubeConfig(out, home, getenv)
	if err != nil {
		t.Fatal(err)
	}
	if len(k.Clusters) != 3 {
		t.Fatalf("clusters: %+v", k.Clusters)
	}
	kind, prod, private := k.Clusters[0], k.Clusters[1], k.Clusters[2]
	if private.Addr() != "[fd00::5]:6443" || private.Alias != "fd00--5.kube.opfence.invalid" || private.RootCAs == nil {
		t.Errorf("private: %+v", private)
	}
	if kind.Addr() != "127.0.0.1:6443" || kind.ServerName != "127.0.0.1" || kind.Alias != "127-0-0-1.kube.opfence.invalid" ||
		kind.RootCAs == nil || kind.Insecure || len(kind.ClientCerts) != 1 {
		t.Errorf("kind: %+v", kind)
	}
	if prod.Addr() != "prod.example.com:443" || prod.ServerName != "api.prod.internal" || prod.Alias != "" || !prod.Insecure ||
		prod.RootCAs != nil || len(prod.ClientCerts) != 0 {
		t.Errorf("prod: %+v", prod)
	}
	for _, name := range []string{"127.0.0.1", "127-0-0-1.kube.opfence.invalid", "prod.example.com", "api.prod.internal", "fd00::5", "fd00--5.kube.opfence.invalid"} {
		if !k.CA.Permits(name) {
			t.Errorf("the session CA does not cover %s", name)
		}
	}
	for _, name := range []string{"example.com", "127.0.0.2", "ignored.example.com"} {
		if k.CA.Permits(name) {
			t.Errorf("the session CA covers %s", name)
		}
	}
	if k.Env["KUBECONFIG"] != k.Path || k.Env["KUBE_FEATURE_ClientsAllowCBOR"] != "false" || !strings.HasPrefix(k.Path, out) {
		t.Errorf("env: %v", k.Env)
	}
	if notes := strings.Join(k.Notes, "\n"); !strings.Contains(notes, "legacy is served over http") || !strings.Contains(notes, "127.0.0.1:6443, [fd00::5]:6443, prod.example.com:443") {
		t.Errorf("notes: %s", notes)
	}

	// The session's kubeconfig.
	data, err := os.ReadFile(k.Path)
	if err != nil {
		t.Fatal(err)
	}
	var doc struct {
		Clusters []struct {
			Name    string         `yaml:"name"`
			Cluster map[string]any `yaml:"cluster"`
		} `yaml:"clusters"`
		Users []struct {
			Name string         `yaml:"name"`
			User map[string]any `yaml:"user"`
		} `yaml:"users"`
		Contexts []map[string]any `yaml:"contexts"`
		Current  string           `yaml:"current-context"`
		Prefs    map[string]any   `yaml:"preferences"`
	}
	if err := yaml.Unmarshal(data, &doc); err != nil {
		t.Fatal(err)
	}
	if doc.Current != "kind" || doc.Prefs == nil || len(doc.Clusters) != 4 || len(doc.Users) != 2 || len(doc.Contexts) != 2 {
		t.Fatalf("session kubeconfig:\n%s", data)
	}
	caData := base64.StdEncoding.EncodeToString(k.CA.CertPEM())
	want := map[string]map[string]any{
		"kind":    {"server": "https://127-0-0-1.kube.opfence.invalid:6443", "certificate-authority-data": caData},
		"prod":    {"server": "https://Prod.Example.com", "tls-server-name": "api.prod.internal", "certificate-authority-data": caData},
		"legacy":  {"server": "http://10.0.0.5:8080"},
		"private": {"server": "https://fd00--5.kube.opfence.invalid:6443", "certificate-authority-data": caData},
	}
	for _, c := range doc.Clusters {
		if len(c.Cluster) != len(want[c.Name]) {
			t.Errorf("cluster %s: %v", c.Name, c.Cluster)
		}
		for key, v := range want[c.Name] {
			if c.Cluster[key] != v {
				t.Errorf("cluster %s %s = %v, want %v", c.Name, key, c.Cluster[key], v)
			}
		}
	}
	for _, u := range doc.Users {
		switch u.Name {
		case "kind-admin":
			if u.User["client-certificate"] != filepath.Join(dir, "admin.crt") || u.User["client-key"] != filepath.Join(dir, "admin.key") {
				t.Errorf("kind-admin: %v", u.User)
			}
		case "prod-user":
			ex, _ := u.User["exec"].(map[string]any)
			if u.User["token"] != "real-token" || ex["command"] != filepath.Join(dir, "bin", "plugin") {
				t.Errorf("prod-user: %v", u.User)
			}
		}
	}
	info, err := os.Stat(k.Path)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Errorf("the session kubeconfig's mode: %v %v", info, err)
	}
}

func TestKubeConfigErrors(t *testing.T) {
	dir := t.TempDir()
	for name, cfg := range map[string]string{
		"one server, two names": "clusters:\n- name: a\n  cluster: {server: https://k.example.com, tls-server-name: x.example.com}\n" +
			"- name: b\n  cluster: {server: https://k.example.com:443}\n",
		"a CA that is not PEM": "clusters:\n- name: a\n  cluster: {server: https://k.example.com, certificate-authority-data: bm90IGEgY2VydA==}\n",
		"a missing CA file":    "clusters:\n- name: a\n  cluster: {server: https://k.example.com, certificate-authority: nope.crt}\n",
		"a broken client key": "clusters:\n- name: a\n  cluster: {server: https://k.example.com}\nusers:\n- name: u\n  user: {client-certificate-data: eA==, client-key-data: eA==}\n" +
			"contexts:\n- name: c\n  context: {cluster: a, user: u}\n",
		"not YAML": "clusters: [",
	} {
		p := filepath.Join(dir, strings.ReplaceAll(name, " ", "-")+".yaml")
		if err := os.WriteFile(p, []byte(cfg), 0o600); err != nil {
			t.Fatal(err)
		}
		if _, err := KubeConfig(t.TempDir(), "", func(k string) string {
			if k == "KUBECONFIG" {
				return p
			}
			return ""
		}); err == nil {
			t.Errorf("%s: no error", name)
		}
	}
	// Only plain HTTP clusters: nothing to intercept.
	p := filepath.Join(dir, "plain.yaml")
	if err := os.WriteFile(p, []byte("clusters:\n- name: a\n  cluster: {server: http://k.example.com}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if k, err := KubeConfig(t.TempDir(), "", func(k string) string {
		if k == "KUBECONFIG" {
			return p
		}
		return ""
	}); k != nil || err != nil {
		t.Errorf("plain HTTP only: %v %v", k, err)
	}
}
