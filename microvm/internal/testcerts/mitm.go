package testcerts

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
	"sync/atomic"
	"time"
)

// Name returns the CommonName of the CA.
func (c *CA) Name() string { return c.cert.Subject.CommonName }

// ServerCert returns a TLS server certificate for host (a DNS name or an IP)
// signed by the CA.
func (c *CA) ServerCert(host string) (tls.Certificate, error) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return tls.Certificate{}, err
	}
	tpl := &x509.Certificate{
		SerialNumber: big.NewInt(time.Now().UnixNano()), Subject: pkix.Name{CommonName: host},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(24 * time.Hour),
		KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	if ip := net.ParseIP(host); ip != nil {
		tpl.IPAddresses = []net.IP{ip}
	} else {
		tpl.DNSNames = []string{host}
	}
	der, err := x509.CreateCertificate(rand.Reader, tpl, c.cert, &key.PublicKey, c.key)
	if err != nil {
		return tls.Certificate{}, err
	}
	return tls.Certificate{Certificate: [][]byte{der}, PrivateKey: key}, nil
}

// MITM is a TLS-intercepting HTTP proxy for egress tests, like
// sandbox-proxy. It answers CONNECT, ends TLS with a certificate from its
// current CA and replies "mitm-ok <CA name> <host>" to every request, with
// no upstream.
type MITM struct {
	ca atomic.Pointer[CA]
	// Requests counts the HTTPS requests that it answered.
	Requests atomic.Int64
}

// NewMITM returns a MITM that signs with ca.
func NewMITM(ca *CA) *MITM {
	m := &MITM{}
	m.ca.Store(ca)
	return m
}

// SetCA changes the signing CA for new connections.
func (m *MITM) SetCA(ca *CA) { m.ca.Store(ca) }

// Serve answers connections on ln until ln closes.
func (m *MITM) Serve(ln net.Listener) {
	for {
		c, err := ln.Accept()
		if err != nil {
			return
		}
		go m.handle(c)
	}
}

type readConn struct {
	net.Conn
	r io.Reader
}

func (c readConn) Read(p []byte) (int, error) { return c.r.Read(p) }

func (m *MITM) handle(c net.Conn) {
	defer func() { _ = c.Close() }()
	_ = c.SetDeadline(time.Now().Add(time.Minute))
	br := bufio.NewReader(c)
	req, err := http.ReadRequest(br)
	if err != nil {
		return
	}
	if req.Method != http.MethodConnect {
		_, _ = io.WriteString(c, "HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
		return
	}
	host, _, err := net.SplitHostPort(req.Host)
	if err != nil {
		host = req.Host
	}
	if _, err := io.WriteString(c, "HTTP/1.1 200 Connection established\r\n\r\n"); err != nil {
		return
	}
	ca := m.ca.Load()
	cert, err := ca.ServerCert(host)
	if err != nil {
		return
	}
	tc := tls.Server(readConn{Conn: c, r: br}, &tls.Config{Certificates: []tls.Certificate{cert}, MinVersion: tls.VersionTLS12})
	if err := tc.Handshake(); err != nil {
		return
	}
	in, err := http.ReadRequest(bufio.NewReader(tc))
	if err != nil {
		return
	}
	_ = in.Body.Close()
	m.Requests.Add(1)
	body := fmt.Sprintf("mitm-ok %s %s\n", ca.Name(), host)
	_, _ = fmt.Fprintf(tc, "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s", len(body), body)
	_ = tc.Close()
}
