// Package egressca reads and checks the deployment egress CA: the public
// certificate of the sandbox-proxy CA that VMs must trust (ENG-4648).
//
// The root drive has no CA. The agent reads the CA at each Create and sends
// it to the guest daemon with SetKey; the daemon installs it at Init.
package egressca

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/pem"
	"errors"
	"fmt"
	"os"
	"strings"
	"sync"
	"time"
)

// MaxPEMBytes is the largest CA PEM that the agent and the daemon accept.
const MaxPEMBytes = 16 << 10

// CA is one checked egress CA.
type CA struct {
	// PEM is the one CERTIFICATE block, re-encoded (no other text).
	PEM []byte
	// Fingerprint is the SHA256 of the DER, lower-case hex.
	Fingerprint string
	Cert        *x509.Certificate
}

// Parse checks that raw is exactly one PEM CA certificate with no private
// key, and returns it.
func Parse(raw []byte) (*CA, error) {
	if len(raw) > MaxPEMBytes {
		return nil, fmt.Errorf("the CA PEM is %d bytes, the limit is %d", len(raw), MaxPEMBytes)
	}
	if bytes.Contains(raw, []byte("PRIVATE KEY")) {
		return nil, errors.New("the CA PEM has a private key; pass the public certificate only")
	}
	block, rest := pem.Decode(raw)
	if block == nil || block.Type != "CERTIFICATE" {
		return nil, errors.New("no PEM certificate")
	}
	if b2, _ := pem.Decode(rest); b2 != nil {
		return nil, errors.New("more than one PEM block")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return nil, err
	}
	if !cert.IsCA {
		return nil, errors.New("not a CA certificate")
	}
	sum := sha256.Sum256(block.Bytes)
	return &CA{
		PEM:         pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: block.Bytes}),
		Fingerprint: hex.EncodeToString(sum[:]),
		Cert:        cert,
	}, nil
}

// Source returns the current egress CA.
type Source interface {
	CA(ctx context.Context) (*CA, error)
	// String names the source for logs.
	String() string
}

// File reads the CA from a file at each call. A mounted ConfigMap or Secret
// file changes in place, so a new CA needs no restart.
type File struct{ Path string }

func (f File) String() string { return "file " + f.Path }

// CA implements Source.
func (f File) CA(context.Context) (*CA, error) {
	raw, err := os.ReadFile(f.Path)
	if err != nil {
		return nil, err
	}
	ca, err := Parse(raw)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", f.Path, err)
	}
	return ca, nil
}

// ConfigMapGetter reads the data of one ConfigMap.
type ConfigMapGetter interface {
	ConfigMap(ctx context.Context, namespace, name string) (map[string]string, error)
}

// ConfigMap reads the CA from a key of a ConfigMap through the Kubernetes
// API (the sandbox-proxy CA bundle ConfigMap is in another namespace, so the
// agent pod cannot mount it).
type ConfigMap struct {
	Getter          ConfigMapGetter
	Namespace, Name string
	Key             string
}

func (c ConfigMap) String() string {
	return "configmap " + c.Namespace + "/" + c.Name + " key " + c.Key
}

// CA implements Source.
func (c ConfigMap) CA(ctx context.Context) (*CA, error) {
	data, err := c.Getter.ConfigMap(ctx, c.Namespace, c.Name)
	if err != nil {
		return nil, err
	}
	v, ok := data[c.Key]
	if !ok {
		return nil, fmt.Errorf("configmap %s/%s has no key %s", c.Namespace, c.Name, c.Key)
	}
	ca, err := Parse([]byte(v))
	if err != nil {
		return nil, fmt.Errorf("configmap %s/%s key %s: %w", c.Namespace, c.Name, c.Key, err)
	}
	return ca, nil
}

// ParseConfigMapRef parses "<namespace>/<name>" or "<namespace>/<name>:<key>"
// (default key ca.crt).
func ParseConfigMapRef(ref string) (namespace, name, key string, err error) {
	key = "ca.crt"
	if i := strings.LastIndex(ref, ":"); i >= 0 {
		ref, key = ref[:i], ref[i+1:]
	}
	namespace, name, ok := strings.Cut(ref, "/")
	if !ok || namespace == "" || name == "" || key == "" || strings.Contains(name, "/") {
		return "", "", "", fmt.Errorf("want <namespace>/<name>[:<key>], got %q", ref)
	}
	return namespace, name, key, nil
}

// Cached keeps the last good CA of Src for TTL. When a read fails, it keeps
// using the last good CA, so a short API outage does not stop Create.
type Cached struct {
	Src Source
	TTL time.Duration
	Now func() time.Time

	mu   sync.Mutex
	last *CA
	at   time.Time
}

func (c *Cached) String() string { return c.Src.String() }

func (c *Cached) now() time.Time {
	if c.Now != nil {
		return c.Now()
	}
	return time.Now()
}

// CA implements Source.
func (c *Cached) CA(ctx context.Context) (*CA, error) {
	ca, _, err := c.Get(ctx)
	return ca, err
}

// Get returns the CA. If a refresh failed and the last good CA is returned,
// refreshErr is that failure.
func (c *Cached) Get(ctx context.Context) (ca *CA, refreshErr error, err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.last != nil && c.now().Sub(c.at) < c.TTL {
		return c.last, nil, nil
	}
	fresh, ferr := c.Src.CA(ctx)
	if ferr == nil {
		c.last, c.at = fresh, c.now()
		return fresh, nil, nil
	}
	if c.last != nil {
		return c.last, ferr, nil
	}
	return nil, nil, ferr
}
