// Package testcerts makes throwaway CAs and certificates for mTLS tests.
package testcerts

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"time"
)

// CA is a test certificate authority.
type CA struct {
	cert *x509.Certificate
	key  *ecdsa.PrivateKey
	// PEM is the CA certificate.
	PEM []byte
}

// NewCA returns a new self-signed CA.
func NewCA(name string) (*CA, error) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	tpl := &x509.Certificate{
		SerialNumber: big.NewInt(time.Now().UnixNano()), Subject: pkix.Name{CommonName: name},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(24 * time.Hour),
		IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature,
	}
	der, err := x509.CreateCertificate(rand.Reader, tpl, tpl, &key.PublicKey, key)
	if err != nil {
		return nil, err
	}
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		return nil, err
	}
	return &CA{cert: cert, key: key, PEM: pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})}, nil
}

// Leaf returns a certificate and key (PEM) signed by the CA. A server leaf
// is valid for 127.0.0.1 and localhost; a client leaf has the URI SAN
// spiffe://test/<name>.
func (c *CA) Leaf(name string, server bool) (certPEM, keyPEM []byte, err error) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, nil, err
	}
	tpl := &x509.Certificate{
		SerialNumber: big.NewInt(time.Now().UnixNano()), Subject: pkix.Name{CommonName: name},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(24 * time.Hour),
		KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}
	if !server {
		tpl.URIs = []*url.URL{{Scheme: "spiffe", Host: "test", Path: "/" + name}}
	}
	if server {
		tpl.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}
		tpl.IPAddresses = []net.IP{net.ParseIP("127.0.0.1")}
		tpl.DNSNames = []string{"localhost"}
	}
	der, err := x509.CreateCertificate(rand.Reader, tpl, c.cert, &key.PublicKey, c.key)
	if err != nil {
		return nil, nil, err
	}
	kder, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		return nil, nil, err
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}),
		pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: kder}), nil
}

// Set is the files of one mTLS test setup.
type Set struct {
	ServerCert, ServerKey, ClientCA string
	// Signed by the api_server CA.
	GoodCert, GoodKey string
	// Signed by the api_server CA, with another identity.
	OtherCert, OtherKey string
	// Signed by another CA.
	BadCert, BadKey string
	// The CA that signed the server certificate, for clients.
	ServerCA string
}

// Write makes a full setup in dir.
func Write(dir string) (*Set, error) {
	nodeCA, err := NewCA("test node CA")
	if err != nil {
		return nil, err
	}
	apiCA, err := NewCA("test api_server CA")
	if err != nil {
		return nil, err
	}
	otherCA, err := NewCA("test other CA")
	if err != nil {
		return nil, err
	}
	s := &Set{}
	files := map[*string][]byte{}
	add := func(dst *string, name string, data []byte) {
		*dst = filepath.Join(dir, name)
		files[dst] = data
	}
	sc, sk, err := nodeCA.Leaf("host-agent", true)
	if err != nil {
		return nil, err
	}
	gc, gk, err := apiCA.Leaf("api_server", false)
	if err != nil {
		return nil, err
	}
	oc, ok, err := apiCA.Leaf("other-client", false)
	if err != nil {
		return nil, err
	}
	bc, bk, err := otherCA.Leaf("api_server", false)
	if err != nil {
		return nil, err
	}
	add(&s.ServerCert, "server.crt", sc)
	add(&s.ServerKey, "server.key", sk)
	add(&s.ClientCA, "api-ca.crt", apiCA.PEM)
	add(&s.ServerCA, "node-ca.crt", nodeCA.PEM)
	add(&s.GoodCert, "good.crt", gc)
	add(&s.GoodKey, "good.key", gk)
	add(&s.OtherCert, "other.crt", oc)
	add(&s.OtherKey, "other.key", ok)
	add(&s.BadCert, "bad.crt", bc)
	add(&s.BadKey, "bad.key", bk)
	for p, data := range files {
		if err := os.WriteFile(*p, data, 0o600); err != nil {
			return nil, err
		}
	}
	return s, nil
}
