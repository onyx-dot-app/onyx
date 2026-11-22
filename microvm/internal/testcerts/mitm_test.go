package testcerts

import (
	"crypto/tls"
	"crypto/x509"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"testing"
)

func TestMITM(t *testing.T) {
	ca1, err := NewCA("egress one")
	if err != nil {
		t.Fatal(err)
	}
	ca2, err := NewCA("egress two")
	if err != nil {
		t.Fatal(err)
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = ln.Close() }()
	m := NewMITM(ca1)
	go m.Serve(ln)
	get := func(trust *CA) (string, error) {
		pool := x509.NewCertPool()
		pool.AppendCertsFromPEM(trust.PEM)
		c := &http.Client{Transport: &http.Transport{
			Proxy:           http.ProxyURL(&url.URL{Scheme: "http", Host: ln.Addr().String()}),
			TLSClientConfig: &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS12},
		}}
		r, err := c.Get("https://example.com/")
		if err != nil {
			return "", err
		}
		defer func() { _ = r.Body.Close() }()
		b, err := io.ReadAll(r.Body)
		return string(b), err
	}
	if body, err := get(ca1); err != nil || body != "mitm-ok egress one example.com\n" {
		t.Fatalf("trusted: %q %v", body, err)
	}
	if _, err := get(ca2); err == nil || !strings.Contains(err.Error(), "certificate") {
		t.Fatalf("untrusted CA: %v", err)
	}
	m.SetCA(ca2)
	if body, err := get(ca2); err != nil || !strings.Contains(body, "egress two") {
		t.Fatalf("after SetCA: %q %v", body, err)
	}
	if m.Requests.Load() != 2 {
		t.Fatalf("requests %d", m.Requests.Load())
	}
}
