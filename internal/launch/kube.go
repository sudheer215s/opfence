package launch

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"

	"go.yaml.in/yaml/v3"

	"github.com/rakeshnitb23/opfence/internal/ca"
)

// KubeSession is what KubeConfig prepared for one session (stage 31c):
// kubectl and other clients reach the user's clusters through Opfence,
// trusting a session CA for them.
type KubeSession struct {
	// Env points clients at the session's kubeconfig (KUBECONFIG) and keeps
	// client-go's CBOR encoding off, so request bodies stay readable.
	Env map[string]string
	// Clusters are the API servers the proxy intercepts.
	Clusters []*KubeCluster
	// CA signs the proxy's certificates for the clusters; the session's
	// kubeconfig trusts it and nothing else for them.
	CA *ca.CA
	// Path is the session's kubeconfig.
	Path string
	// Notes say what was set up and what was not, for the banner.
	Notes []string
}

// KubeCluster is one API server of the user's kubeconfig.
type KubeCluster struct {
	Names      []string // the kubeconfig's names for it
	Host, Port string   // from its server URL
	// ServerName is the name its certificate is checked against: the
	// kubeconfig's tls-server-name, or Host.
	ServerName string
	// Alias, for a server named by an IP address or localhost, is the name
	// the session's kubeconfig calls it instead: clients reach loopback
	// and private addresses directly (NO_PROXY: Opfence's lists loopback,
	// the sandbox runtime's the private ranges too), and this name, under
	// .invalid, goes through the proxy, which knows it.
	Alias string
	// RootCAs is the cluster's own CA; nil means the system's roots.
	RootCAs *x509.CertPool
	// Insecure is the kubeconfig's insecure-skip-tls-verify.
	Insecure bool
	// ClientCerts are the client certificates of the users the
	// kubeconfig's contexts pair with this cluster. A client presents one
	// to the proxy, which presents it to the cluster.
	ClientCerts []tls.Certificate
}

// Addr is the cluster's host and port.
func (c *KubeCluster) Addr() string { return net.JoinHostPort(c.Host, c.Port) }

// kubeFile is one kubeconfig file, generically: unknown fields survive.
type kubeFile struct {
	path string
	doc  map[string]any
}

// KubeConfig reads the user's kubeconfig (KUBECONFIG's files, merged as
// kubectl merges them, or ~/.kube/config) and writes a session copy into
// dir in which every cluster served over HTTPS trusts a new session CA
// instead of its own, so the proxy can read what clients send it. The
// proxy checks each cluster with its own CA, or with the system's roots, or
// not at all when the kubeconfig says insecure-skip-tls-verify. Credentials
// stay as they are: tokens, exec plugins and client certificates are the
// kubeconfig's. With no kubeconfig, or no HTTPS cluster in it, it returns
// nil.
func KubeConfig(dir, home string, getenv func(string) string) (*KubeSession, error) {
	var paths []string
	if v := getenv("KUBECONFIG"); v != "" {
		for _, p := range filepath.SplitList(v) {
			if p != "" && !slices.Contains(paths, p) {
				paths = append(paths, p)
			}
		}
	} else if home != "" {
		paths = []string{filepath.Join(home, ".kube", "config")}
	}
	var files []kubeFile
	for _, p := range paths {
		data, err := os.ReadFile(p)
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("kubeconfig %s: %w", p, err)
		}
		var doc map[string]any
		if err := yaml.Unmarshal(data, &doc); err != nil {
			return nil, fmt.Errorf("kubeconfig %s: %w", p, err)
		}
		if doc == nil {
			continue
		}
		abs, err := filepath.Abs(p)
		if err != nil {
			return nil, err
		}
		files = append(files, kubeFile{path: abs, doc: doc})
	}
	if len(files) == 0 {
		return nil, nil
	}
	merged := mergeKubeconfigs(files)
	k := &KubeSession{Env: map[string]string{}}

	// The clusters: each HTTPS server once, with its CA.
	byAddr := map[string]*KubeCluster{}
	var names []string
	var ips []net.IP
	clusterOf := map[string]*KubeCluster{} // kubeconfig cluster name -> cluster
	for _, e := range merged.clusters {
		c, _ := e.value["cluster"].(map[string]any)
		server, _ := c["server"].(string)
		u, err := url.Parse(server)
		if err != nil || u.Host == "" {
			k.Notes = append(k.Notes, fmt.Sprintf("cluster %s has a server Opfence cannot read, so it is left as it is", e.name))
			continue
		}
		if u.Scheme != "https" {
			k.Notes = append(k.Notes, fmt.Sprintf("cluster %s is served over %s, which Opfence does not intercept", e.name, u.Scheme))
			continue
		}
		port := u.Port()
		if port == "" {
			port = "443"
		}
		host := strings.ToLower(strings.TrimSuffix(u.Hostname(), "."))
		serverName, _ := c["tls-server-name"].(string)
		if serverName == "" {
			serverName = host
		}
		insecure, _ := c["insecure-skip-tls-verify"].(bool)
		var pool *x509.CertPool
		if pemData, err := kubeData(c, "certificate-authority", e.dir); err != nil {
			return nil, fmt.Errorf("cluster %s: %w", e.name, err)
		} else if pemData != nil {
			pool = x509.NewCertPool()
			if !pool.AppendCertsFromPEM(pemData) {
				return nil, fmt.Errorf("cluster %s: its certificate authority holds no PEM certificate", e.name)
			}
		}
		addr := net.JoinHostPort(host, port)
		kc := byAddr[addr]
		if kc == nil {
			kc = &KubeCluster{Host: host, Port: port, ServerName: strings.ToLower(serverName), RootCAs: pool, Insecure: insecure}
			byAddr[addr] = kc
			k.Clusters = append(k.Clusters, kc)
		} else if kc.ServerName != strings.ToLower(serverName) || kc.Insecure != insecure {
			return nil, fmt.Errorf("clusters %s and %s name the same server %s differently", kc.Names[0], e.name, addr)
		}
		kc.Names = append(kc.Names, e.name)
		clusterOf[e.name] = kc
		if needsAlias(host) {
			kc.Alias = strings.NewReplacer(".", "-", ":", "-").Replace(host) + ".kube.opfence.invalid"
		}
		for _, n := range []string{host, kc.ServerName, kc.Alias} {
			if n == "" {
				continue
			}
			if ip := net.ParseIP(n); ip != nil {
				if !slices.ContainsFunc(ips, ip.Equal) {
					ips = append(ips, ip)
				}
			} else if !slices.Contains(names, n) {
				names = append(names, n)
			}
		}
	}
	if len(k.Clusters) == 0 {
		return nil, nil
	}

	// The users' client certificates, for the clusters contexts pair them
	// with.
	users := map[string]map[string]any{}
	userDir := map[string]string{}
	for _, e := range merged.users {
		u, _ := e.value["user"].(map[string]any)
		users[e.name], userDir[e.name] = u, e.dir
	}
	for _, e := range merged.contexts {
		ctx, _ := e.value["context"].(map[string]any)
		cname, _ := ctx["cluster"].(string)
		uname, _ := ctx["user"].(string)
		kc, u := clusterOf[cname], users[uname]
		if kc == nil || u == nil {
			continue
		}
		certPEM, err := kubeData(u, "client-certificate", userDir[uname])
		if err != nil {
			return nil, fmt.Errorf("user %s: %w", uname, err)
		}
		keyPEM, err := kubeData(u, "client-key", userDir[uname])
		if err != nil {
			return nil, fmt.Errorf("user %s: %w", uname, err)
		}
		if certPEM == nil || keyPEM == nil {
			continue
		}
		cert, err := tls.X509KeyPair(certPEM, keyPEM)
		if err != nil {
			return nil, fmt.Errorf("user %s: client certificate: %w", uname, err)
		}
		if !slices.ContainsFunc(kc.ClientCerts, func(c tls.Certificate) bool { return string(c.Certificate[0]) == string(cert.Certificate[0]) }) {
			kc.ClientCerts = append(kc.ClientCerts, cert)
		}
	}

	var err error
	if k.CA, err = ca.NewSession(names, ips); err != nil {
		return nil, err
	}
	caData := base64.StdEncoding.EncodeToString(k.CA.CertPEM())

	// The session's kubeconfig: the merged one, its HTTPS clusters trusting
	// the session CA and every relative path made absolute.
	out := map[string]any{}
	for key, v := range merged.top {
		out[key] = v
	}
	var clusters, usersOut, contexts []any
	for _, e := range merged.clusters {
		c, _ := e.value["cluster"].(map[string]any)
		nc := map[string]any{}
		for key, v := range c {
			nc[key] = v
		}
		if kc := clusterOf[e.name]; kc != nil {
			delete(nc, "certificate-authority")
			delete(nc, "insecure-skip-tls-verify")
			nc["certificate-authority-data"] = caData
			if kc.Alias != "" {
				u, _ := url.Parse(nc["server"].(string))
				u.Host = net.JoinHostPort(kc.Alias, kc.Port)
				nc["server"] = u.String()
			}
		} else if p, ok := nc["certificate-authority"].(string); ok {
			nc["certificate-authority"] = absUnder(e.dir, p)
		}
		clusters = append(clusters, withValue(e.value, "cluster", nc))
	}
	for _, e := range merged.users {
		u, _ := e.value["user"].(map[string]any)
		nu := map[string]any{}
		for key, v := range u {
			nu[key] = v
		}
		for _, f := range []string{"client-certificate", "client-key", "tokenFile"} {
			if p, ok := nu[f].(string); ok {
				nu[f] = absUnder(e.dir, p)
			}
		}
		if ex, ok := nu["exec"].(map[string]any); ok {
			// kubectl runs a command with a slash in its name from the
			// kubeconfig's folder.
			if cmd, ok := ex["command"].(string); ok && strings.ContainsRune(cmd, '/') && !filepath.IsAbs(cmd) {
				nex := map[string]any{}
				for key, v := range ex {
					nex[key] = v
				}
				nex["command"] = absUnder(e.dir, cmd)
				nu["exec"] = nex
			}
		}
		usersOut = append(usersOut, withValue(e.value, "user", nu))
	}
	for _, e := range merged.contexts {
		contexts = append(contexts, e.value)
	}
	out["clusters"], out["users"], out["contexts"] = clusters, usersOut, contexts
	if merged.current != "" {
		out["current-context"] = merged.current
	}
	if out["apiVersion"] == nil {
		out["apiVersion"] = "v1"
	}
	if out["kind"] == nil {
		out["kind"] = "Config"
	}
	data, err := yaml.Marshal(out)
	if err != nil {
		return nil, err
	}
	kdir := filepath.Join(dir, "kube")
	if err := os.MkdirAll(kdir, 0o700); err != nil {
		return nil, err
	}
	k.Path = filepath.Join(kdir, "config")
	if err := os.WriteFile(k.Path, data, 0o600); err != nil {
		return nil, err
	}
	k.Env["KUBECONFIG"] = k.Path
	// client-go's CBOR (an alpha feature, off by default) would make
	// bodies Opfence cannot read.
	k.Env["KUBE_FEATURE_ClientsAllowCBOR"] = "false"
	k.Env["KUBE_FEATURE_ClientsPreferCBOR"] = "false"

	var shown []string
	for _, c := range k.Clusters {
		shown = append(shown, c.Addr())
	}
	sort.Strings(shown)
	k.Notes = append(k.Notes, fmt.Sprintf("kubectl reaches %d Kubernetes API server(s) through Opfence: %s", len(shown), strings.Join(shown, ", ")))
	return k, nil
}

// kubeEntry is a named entry of a kubeconfig list, with the folder of the
// file that defined it.
type kubeEntry struct {
	name  string
	value map[string]any
	dir   string
}

type mergedKube struct {
	top                       map[string]any
	clusters, users, contexts []kubeEntry
	current                   string
}

// mergeKubeconfigs merges files as kubectl does: the first file to define
// a cluster, user or context by name wins, and so does the first to set
// current-context.
func mergeKubeconfigs(files []kubeFile) mergedKube {
	m := mergedKube{top: map[string]any{}}
	seen := map[string]map[string]bool{"clusters": {}, "users": {}, "contexts": {}}
	for _, f := range files {
		dir := filepath.Dir(f.path)
		for key, v := range f.doc {
			switch key {
			case "clusters", "users", "contexts":
				list, _ := v.([]any)
				for _, item := range list {
					e, _ := item.(map[string]any)
					name, _ := e["name"].(string)
					if name == "" || seen[key][name] {
						continue
					}
					seen[key][name] = true
					ke := kubeEntry{name: name, value: e, dir: dir}
					switch key {
					case "clusters":
						m.clusters = append(m.clusters, ke)
					case "users":
						m.users = append(m.users, ke)
					default:
						m.contexts = append(m.contexts, ke)
					}
				}
			case "current-context":
				if s, _ := v.(string); s != "" && m.current == "" {
					m.current = s
				}
			default:
				if _, ok := m.top[key]; !ok {
					m.top[key] = v
				}
			}
		}
	}
	return m
}

// kubeData reads a kubeconfig field given inline (<field>-data, base64) or
// as a file (<field>, relative to the kubeconfig's folder). It returns nil
// when neither is set.
func kubeData(m map[string]any, field, dir string) ([]byte, error) {
	if s, _ := m[field+"-data"].(string); s != "" {
		b, err := base64.StdEncoding.DecodeString(strings.TrimSpace(s))
		if err != nil {
			return nil, fmt.Errorf("%s-data: %w", field, err)
		}
		return b, nil
	}
	if p, _ := m[field].(string); p != "" {
		b, err := os.ReadFile(absUnder(dir, p))
		if err != nil {
			return nil, fmt.Errorf("%s: %w", field, err)
		}
		return b, nil
	}
	return nil, nil
}

// needsAlias reports whether a client could skip the proxy for host: an IP
// address (NO_PROXY lists address ranges, never names it does not know) or
// localhost.
func needsAlias(host string) bool {
	return net.ParseIP(host) != nil || host == "localhost" || strings.HasSuffix(host, ".localhost")
}

func absUnder(dir, p string) string {
	if strings.HasPrefix(p, "~/") {
		if home, err := os.UserHomeDir(); err == nil {
			return filepath.Join(home, p[2:])
		}
	}
	if filepath.IsAbs(p) {
		return p
	}
	return filepath.Join(dir, p)
}

func withValue(entry map[string]any, key string, v map[string]any) map[string]any {
	out := map[string]any{}
	for k, x := range entry {
		out[k] = x
	}
	out[key] = v
	return out
}
