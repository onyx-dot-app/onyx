package relay

import (
	"bufio"
	"crypto/tls"
	"crypto/x509"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
)

const proxyName = "onyx-sandbox-proxy.onyx.svc"

// tlsPKI is one relay → proxy mTLS setup: a proxy CA, a relay client CA, and
// a CA that neither side trusts.
type tlsPKI struct {
	proxyCA, relayCA, otherCA *testcerts.CA
	dir                       string
}

func newTLSPKI(t *testing.T) *tlsPKI {
	t.Helper()
	p := &tlsPKI{dir: t.TempDir()}
	for dst, name := range map[**testcerts.CA]string{&p.proxyCA: "proxy CA", &p.relayCA: "relay CA", &p.otherCA: "other CA"} {
		ca, err := testcerts.NewCA(name)
		if err != nil {
			t.Fatal(err)
		}
		*dst = ca
	}
	return p
}

func (p *tlsPKI) write(t *testing.T, name string, data []byte) string {
	t.Helper()
	path := filepath.Join(p.dir, name)
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

// relayTLS is the relay side: it trusts trust and shows a client cert from signer.
func (p *tlsPKI) relayTLS(t *testing.T, trust, signer *testcerts.CA) *UpstreamTLS {
	t.Helper()
	cert, key, err := signer.Leaf("craft-fc-relay", false)
	if err != nil {
		t.Fatal(err)
	}
	tag := strings.ReplaceAll(trust.Name()+"-"+signer.Name(), " ", "_")
	return &UpstreamTLS{
		CAFile: p.write(t, tag+"-ca.crt", trust.PEM), CertFile: p.write(t, tag+".crt", cert),
		KeyFile: p.write(t, tag+".key", key), ServerName: proxyName,
	}
}

// tlsUpstream is newUpstream behind an mTLS listener that requires a client
// cert from clientCA, like the sandbox-proxy relay port. The channel gets
// one value per connection that passed the handshake.
func tlsUpstream(t *testing.T, serverCA *testcerts.CA, serverName string, clientCA *testcerts.CA) (*upstream, chan struct{}) {
	t.Helper()
	cert, err := serverCA.ServerCert(serverName)
	if err != nil {
		t.Fatal(err)
	}
	pool := x509.NewCertPool()
	pool.AppendCertsFromPEM(clientCA.PEM)
	ln, err := tls.Listen("tcp", "127.0.0.1:0", &tls.Config{
		Certificates: []tls.Certificate{cert}, ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: pool,
		MinVersion: tls.VersionTLS13,
	})
	if err != nil {
		t.Fatal(err)
	}
	u := &upstream{ln: ln}
	handshakes := make(chan struct{}, 16)
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
				if err := c.(*tls.Conn).Handshake(); err != nil {
					_ = c.Close()
					return
				}
				handshakes <- struct{}{}
				u.serve(c)
			}()
		}
	}()
	t.Cleanup(func() { _ = ln.Close() })
	return u, handshakes
}

// tunnel sends a CONNECT through the relay and returns the status, or ""
// if the relay closed the connection first.
func tunnel(t *testing.T, sock string) string {
	t.Helper()
	c, err := net.Dial("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	_ = c.SetDeadline(time.Now().Add(10 * time.Second))
	_, _ = io.WriteString(c, "CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\nping")
	resp, err := http.ReadResponse(bufio.NewReader(c), &http.Request{Method: http.MethodConnect})
	if err != nil {
		return ""
	}
	return resp.Status
}

func TestUpstreamTLSStampsOverMTLS(t *testing.T) {
	p := newTLSPKI(t)
	up, handshakes := tlsUpstream(t, p.proxyCA, proxyName, p.relayCA)
	_, sock, _ := newRelay(t, up, func(r *Relay) { r.TLS = p.relayTLS(t, p.proxyCA, p.relayCA) })

	if got := tunnel(t, sock); got != "200 Connection established" {
		t.Fatalf("status %q", got)
	}
	if len(handshakes) != 1 || !strings.Contains(up.lastHead(), "Proxy-Authorization: Bearer ") {
		t.Fatalf("handshakes %d, head %q", len(handshakes), up.lastHead())
	}
}

// TestUpstreamTLSRefuses: each bad setup fails the connection before the
// proxy reads a head, and the relay never retries in plain TCP.
func TestUpstreamTLSRefuses(t *testing.T) {
	p := newTLSPKI(t)
	cases := map[string]struct {
		serverName string
		trust      *testcerts.CA
		signer     *testcerts.CA
		plain      bool
	}{
		// The relay trusts another CA than the one of the proxy cert.
		"bad CA": {serverName: proxyName, trust: p.otherCA, signer: p.relayCA},
		// The proxy cert is valid but for another name.
		"wrong SAN": {serverName: "other.onyx.svc", trust: p.proxyCA, signer: p.relayCA},
		// The proxy does not accept the relay's client cert.
		"untrusted client cert": {serverName: proxyName, trust: p.proxyCA, signer: p.otherCA},
		// The upstream speaks plain TCP: no fallback.
		"plain upstream": {trust: p.proxyCA, signer: p.relayCA, plain: true},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			var up *upstream
			handshakes := make(chan struct{}, 16)
			if c.plain {
				up = newUpstream(t)
			} else {
				up, handshakes = tlsUpstream(t, p.proxyCA, c.serverName, p.relayCA)
			}
			_, sock, _ := newRelay(t, up, func(r *Relay) {
				r.TLS = p.relayTLS(t, c.trust, c.signer)
				r.DialTimeout = time.Second
			})

			// Every refusal is a 502 to the VM, also a client certificate that
			// the proxy refuses after the TLS 1.3 handshake.
			if got := tunnel(t, sock); got != "502 Bad Gateway" {
				t.Fatalf("status %q", got)
			}
			if len(handshakes) != 0 {
				t.Fatalf("%d handshakes passed", len(handshakes))
			}
			up.mu.Lock()
			heads := strings.Join(up.heads, "")
			up.mu.Unlock()
			if strings.Contains(heads, "Proxy-Authorization") || strings.Contains(heads, "CONNECT") {
				t.Fatalf("the proxy read a head: %q", heads)
			}
		})
	}
}

func TestUpstreamTLSCheck(t *testing.T) {
	p := newTLSPKI(t)
	good := p.relayTLS(t, p.proxyCA, p.relayCA)
	if err := good.Check(); err != nil {
		t.Fatal(err)
	}
	for name, u := range map[string]*UpstreamTLS{
		"no client cert": {CAFile: good.CAFile, ServerName: proxyName},
		"no server name": {CAFile: good.CAFile, CertFile: good.CertFile, KeyFile: good.KeyFile},
		"no CA":          {CertFile: good.CertFile, KeyFile: good.KeyFile, ServerName: proxyName},
		"key mismatch":   {CAFile: good.CAFile, CertFile: good.CertFile, KeyFile: good.CAFile, ServerName: proxyName},
	} {
		if err := u.Check(); err == nil {
			t.Errorf("%s: Check passed", name)
		}
	}
}

// TestUpstreamTLSReloadsRotatedFiles: a rotated proxy CA applies at the next
// connection, without a restart.
func TestUpstreamTLSReloadsRotatedFiles(t *testing.T) {
	p := newTLSPKI(t)
	up, _ := tlsUpstream(t, p.otherCA, proxyName, p.relayCA)
	u := p.relayTLS(t, p.proxyCA, p.relayCA)
	_, sock, _ := newRelay(t, up, func(r *Relay) { r.TLS = u; r.DialTimeout = time.Second })
	if got := tunnel(t, sock); got == "200 Connection established" {
		t.Fatal("the relay trusted a proxy CA that it does not have")
	}
	if err := os.WriteFile(u.CAFile, p.otherCA.PEM, 0o600); err != nil {
		t.Fatal(err)
	}
	future := time.Now().Add(time.Hour)
	if err := os.Chtimes(u.CAFile, future, future); err != nil {
		t.Fatal(err)
	}
	if got := tunnel(t, sock); got != "200 Connection established" {
		t.Fatalf("after the rotation: %q", got)
	}
}
