package ca

import (
	"crypto/x509"
	"net"
	"reflect"
	"testing"
	"time"
)

func TestPermittedDomains(t *testing.T) {
	got := PermittedDomains([]string{"*.amazonaws.com", "s3.us-east-1.amazonaws.com", "api.github.com", "API.GitHub.com.", "10.0.0.1", "backboard.railway.com",
		"api.*.neon.tech", "apiauth.*.neon.tech", "console.neon.tech"})
	want := []string{"amazonaws.com", "api.github.com", "backboard.railway.com", "neon.tech"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestLeafVerifies(t *testing.T) {
	c, err := New("test", []string{"api.github.com", "amazonaws.com"})
	if err != nil {
		t.Fatal(err)
	}
	for _, host := range []string{"api.github.com", "s3.us-east-1.amazonaws.com"} {
		l, err := c.Leaf(host)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := l.Leaf.Verify(x509.VerifyOptions{DNSName: host, Roots: c.Pool()}); err != nil {
			t.Fatalf("%s: %v", host, err)
		}
	}
	for _, host := range []string{"example.com", "github.com", "10.0.0.1", ""} {
		if _, err := c.Leaf(host); err == nil {
			t.Errorf("minted a leaf for %q", host)
		}
	}
}

// The name constraints hold even if the key is used directly: a leaf for a
// name outside them, signed by the root, fails verification.
func TestNameConstraintsEnforced(t *testing.T) {
	c, err := New("test", []string{"api.github.com"})
	if err != nil {
		t.Fatal(err)
	}
	c.cert.PermittedDNSDomains = append(c.cert.PermittedDNSDomains, "example.com") // bypass Permits only
	l, err := c.Leaf("example.com")
	if err != nil {
		t.Fatal(err)
	}
	root, _ := x509.ParseCertificate(c.cert.Raw) // the real, signed constraints
	pool := x509.NewCertPool()
	pool.AddCert(root)
	if _, err := l.Leaf.Verify(x509.VerifyOptions{DNSName: "example.com", Roots: pool}); err == nil {
		t.Fatal("leaf outside the name constraints verified")
	}
}

func TestLeafCacheAndRenewal(t *testing.T) {
	c, err := New("test", []string{"api.github.com"})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	c.now = func() time.Time { return now }
	a, _ := c.Leaf("api.github.com")
	b, _ := c.Leaf("API.github.com.")
	if a != b {
		t.Fatal("leaf not cached")
	}
	now = now.Add(leafValidity - leafRenew/2)
	if d, _ := c.Leaf("api.github.com"); d == a {
		t.Fatal("leaf close to expiry was reused")
	}
}

func TestLoadRoundTrip(t *testing.T) {
	c, err := New("test", []string{"api.github.com"})
	if err != nil {
		t.Fatal(err)
	}
	k, err := c.KeyPEM()
	if err != nil {
		t.Fatal(err)
	}
	d, err := Load(c.CertPEM(), k)
	if err != nil {
		t.Fatal(err)
	}
	l, err := d.Leaf("api.github.com")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := l.Leaf.Verify(x509.VerifyOptions{DNSName: "api.github.com", Roots: c.Pool()}); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(k, c.CertPEM()); err == nil {
		t.Fatal("swapped PEM blocks accepted")
	}
	if _, err := New("x", nil); err == nil {
		t.Fatal("unconstrained CA created")
	}
}

// A root signs no IP address unless it names it: the main CA excludes every
// address, and a session CA permits exactly its clusters'.
func TestIPConstraints(t *testing.T) {
	verify := func(c *CA, host string, ip net.IP) error {
		c.cert.PermittedIPRanges = append(c.cert.PermittedIPRanges, &net.IPNet{IP: net.IPv4zero, Mask: net.CIDRMask(0, 32)}) // bypass Permits only
		defer func() { c.cert.PermittedIPRanges = c.cert.PermittedIPRanges[:len(c.cert.PermittedIPRanges)-1] }()
		l, err := c.Leaf(host)
		if err != nil {
			return err
		}
		root, _ := x509.ParseCertificate(c.cert.Raw)
		pool := x509.NewCertPool()
		pool.AddCert(root)
		_, err = l.Leaf.Verify(x509.VerifyOptions{DNSName: ip.String(), Roots: pool})
		return err
	}
	main, err := New("test", []string{"api.github.com"})
	if err != nil {
		t.Fatal(err)
	}
	if err := verify(main, "10.0.0.1", net.ParseIP("10.0.0.1")); err == nil {
		t.Error("the main CA's key signed an address that verified")
	}
	s, err := NewSession([]string{"kube.example.com"}, []net.IP{net.ParseIP("127.0.0.1"), net.ParseIP("::1")})
	if err != nil {
		t.Fatal(err)
	}
	for _, host := range []string{"127.0.0.1", "::1", "kube.example.com"} {
		l, err := s.Leaf(host)
		if err != nil {
			t.Fatalf("%s: %v", host, err)
		}
		if _, err := l.Leaf.Verify(x509.VerifyOptions{DNSName: host, Roots: s.Pool()}); err != nil {
			t.Errorf("%s: %v", host, err)
		}
	}
	for _, host := range []string{"127.0.0.2", "api.github.com", "example.com"} {
		if _, err := s.Leaf(host); err == nil {
			t.Errorf("session CA minted a leaf for %s", host)
		}
	}
	if err := verify(s, "127.0.0.2", net.ParseIP("127.0.0.2")); err == nil {
		t.Error("the session CA's key signed another address that verified")
	}
	// Addresses only: names are confined to .invalid.
	ipOnly, err := NewSession(nil, []net.IP{net.ParseIP("127.0.0.1")})
	if err != nil {
		t.Fatal(err)
	}
	if ipOnly.Permits("example.com") || !ipOnly.Permits("127.0.0.1") {
		t.Error("an address-only session CA's constraints")
	}
	if _, err := NewSession(nil, nil); err == nil {
		t.Error("an empty session CA")
	}
}
