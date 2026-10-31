// Package ca is Opfence's local certificate authority: a name-constrained
// root that mints short-lived leaf certificates for the API hosts the proxy
// intercepts (docs/ARCHITECTURE.md §8.3).
package ca

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"fmt"
	"math/big"
	"net"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	rootValidity = 10 * 365 * 24 * time.Hour
	// sessionValidity bounds a session CA, which lives in memory for one
	// session; a session that outlives it needs restarting.
	sessionValidity = 30 * 24 * time.Hour
	leafValidity    = 24 * time.Hour
	// leafRenew is how close to expiry a cached leaf is replaced.
	leafRenew = time.Hour
	// maxLeaves bounds the leaf cache; wildcard hosts such as
	// *.amazonaws.com could otherwise grow it without limit.
	maxLeaves = 1024
)

// CA holds the root certificate and key and caches leaf certificates.
type CA struct {
	cert    *x509.Certificate
	certPEM []byte
	key     crypto.Signer
	leafKey crypto.Signer

	mu     sync.Mutex
	leaves map[string]*tls.Certificate

	now func() time.Time
}

// New generates a root whose name constraints permit only the given DNS
// domains (see PermittedDomains) and no IP address. An empty list is an
// error: an unconstrained root would let a leaked key impersonate any site.
func New(machine string, permitted []string) (*CA, error) {
	if len(permitted) == 0 {
		return nil, errors.New("ca: no permitted domains")
	}
	cn := "Opfence local CA"
	if machine != "" {
		cn += " (" + machine + ")"
	}
	return newRoot(cn, permitted, nil, rootValidity)
}

// NewSession generates a root for one session's Kubernetes clusters (stage
// 31c), which kubectl trusts from the session's kubeconfig: its constraints
// permit exactly the clusters' names and addresses. Its key stays in
// memory. With addresses only, it permits names under .invalid, which
// nothing resolves, since a root without a DNS constraint could sign any
// name.
func NewSession(names []string, ips []net.IP) (*CA, error) {
	if len(names) == 0 && len(ips) == 0 {
		return nil, errors.New("ca: no permitted names or addresses")
	}
	if len(names) == 0 {
		names = []string{"invalid"}
	}
	return newRoot("Opfence session CA", names, ips, sessionValidity)
}

func newRoot(cn string, permitted []string, ips []net.IP, validity time.Duration) (*CA, error) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	serial, err := randomSerial()
	if err != nil {
		return nil, err
	}
	now := time.Now()
	tmpl := &x509.Certificate{
		SerialNumber:                serial,
		Subject:                     pkix.Name{CommonName: cn, Organization: []string{"Opfence"}},
		NotBefore:                   now.Add(-time.Hour),
		NotAfter:                    now.Add(validity),
		KeyUsage:                    x509.KeyUsageCertSign | x509.KeyUsageCRLSign,
		BasicConstraintsValid:       true,
		IsCA:                        true,
		MaxPathLenZero:              true,
		PermittedDNSDomainsCritical: true,
		PermittedDNSDomains:         permitted,
	}
	if len(ips) == 0 {
		// Without an IP constraint, a root may sign any address.
		tmpl.ExcludedIPRanges = []*net.IPNet{{IP: net.IPv4zero, Mask: net.CIDRMask(0, 32)}, {IP: net.IPv6zero, Mask: net.CIDRMask(0, 128)}}
	}
	for _, ip := range ips {
		if v4 := ip.To4(); v4 != nil {
			tmpl.PermittedIPRanges = append(tmpl.PermittedIPRanges, &net.IPNet{IP: v4, Mask: net.CIDRMask(32, 32)})
		} else {
			tmpl.PermittedIPRanges = append(tmpl.PermittedIPRanges, &net.IPNet{IP: ip.To16(), Mask: net.CIDRMask(128, 128)})
		}
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, key.Public(), key)
	if err != nil {
		return nil, err
	}
	return fromParts(der, key)
}

// Load restores a CA from PEM-encoded certificate and PKCS #8 key.
func Load(certPEM, keyPEM []byte) (*CA, error) {
	cb, _ := pem.Decode(certPEM)
	if cb == nil || cb.Type != "CERTIFICATE" {
		return nil, errors.New("ca: certificate is not PEM")
	}
	kb, _ := pem.Decode(keyPEM)
	if kb == nil || kb.Type != "PRIVATE KEY" {
		return nil, errors.New("ca: key is not a PEM private key")
	}
	k, err := x509.ParsePKCS8PrivateKey(kb.Bytes)
	if err != nil {
		return nil, fmt.Errorf("ca: key: %w", err)
	}
	signer, ok := k.(crypto.Signer)
	if !ok {
		return nil, errors.New("ca: key cannot sign")
	}
	return fromParts(cb.Bytes, signer)
}

func fromParts(der []byte, key crypto.Signer) (*CA, error) {
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		return nil, err
	}
	if !cert.IsCA {
		return nil, errors.New("ca: certificate is not a CA")
	}
	leafKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	return &CA{
		cert:    cert,
		certPEM: pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}),
		key:     key,
		leafKey: leafKey,
		leaves:  map[string]*tls.Certificate{},
		now:     time.Now,
	}, nil
}

// Certificate returns the root certificate.
func (c *CA) Certificate() *x509.Certificate { return c.cert }

// CertPEM returns the root certificate as PEM, for trust stores and the CA
// environment variables. It never contains the key.
func (c *CA) CertPEM() []byte { return c.certPEM }

// KeyPEM returns the root key as PKCS #8 PEM, for the secret store only.
func (c *CA) KeyPEM() ([]byte, error) {
	der, err := x509.MarshalPKCS8PrivateKey(c.key)
	if err != nil {
		return nil, err
	}
	return pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}), nil
}

// Pool returns a certificate pool holding only the root.
func (c *CA) Pool() *x509.CertPool {
	p := x509.NewCertPool()
	p.AddCert(c.cert)
	return p
}

// Permits reports whether the root's name constraints allow host, a name
// or an IP address.
func (c *CA) Permits(host string) bool {
	host = strings.ToLower(host)
	if ip := net.ParseIP(host); ip != nil {
		for _, r := range c.cert.PermittedIPRanges {
			if r.Contains(ip) {
				return true
			}
		}
		return false
	}
	for _, d := range c.cert.PermittedDNSDomains {
		if host == d || strings.HasSuffix(host, "."+d) {
			return true
		}
	}
	return false
}

// Leaf returns a certificate for host, minting one when none is cached or
// the cached one is close to expiry.
func (c *CA) Leaf(host string) (*tls.Certificate, error) {
	host = strings.TrimSuffix(strings.ToLower(host), ".")
	if host == "" {
		return nil, errors.New("ca: no certificate for an empty name")
	}
	if !c.Permits(host) {
		return nil, fmt.Errorf("ca: %s is outside the CA's permitted names", host)
	}
	now := c.now()
	c.mu.Lock()
	defer c.mu.Unlock()
	if l, ok := c.leaves[host]; ok && now.Add(leafRenew).Before(l.Leaf.NotAfter) {
		return l, nil
	}
	serial, err := randomSerial()
	if err != nil {
		return nil, err
	}
	tmpl := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{CommonName: host},
		NotBefore:    now.Add(-time.Hour),
		NotAfter:     now.Add(leafValidity),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	if ip := net.ParseIP(host); ip != nil {
		tmpl.IPAddresses = []net.IP{ip}
	} else {
		tmpl.DNSNames = []string{host}
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, c.cert, c.leafKey.Public(), c.key)
	if err != nil {
		return nil, err
	}
	leaf, err := x509.ParseCertificate(der)
	if err != nil {
		return nil, err
	}
	if len(c.leaves) >= maxLeaves {
		clear(c.leaves)
	}
	l := &tls.Certificate{Certificate: [][]byte{der, c.cert.Raw}, PrivateKey: c.leafKey, Leaf: leaf}
	c.leaves[host] = l
	return l, nil
}

// PermittedDomains turns catalog host patterns into name constraints:
// "*.amazonaws.com" and "api.*.neon.tech" become "amazonaws.com" and
// "neon.tech" (which cover their subdomains), exact hosts stay, and names
// covered by another entry are dropped.
func PermittedDomains(hosts []string) []string {
	set := map[string]bool{}
	for _, h := range hosts {
		h = strings.TrimSuffix(strings.ToLower(strings.TrimSpace(h)), ".")
		h = strings.TrimPrefix(h, "*.")
		if _, suffix, ok := strings.Cut(h, ".*."); ok {
			h = suffix // label.*.suffix: the CA may sign names under suffix
		}
		if h != "" && net.ParseIP(h) == nil {
			set[h] = true
		}
	}
	var out []string
	for h := range set {
		covered := false
		for d := range set {
			if d != h && strings.HasSuffix(h, "."+d) {
				covered = true
				break
			}
		}
		if !covered {
			out = append(out, h)
		}
	}
	sort.Strings(out)
	return out
}

func randomSerial() (*big.Int, error) {
	return rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 127))
}
