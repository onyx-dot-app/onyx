package server

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"os"
	"slices"
	"sync"
	"time"

	"google.golang.org/grpc/credentials"
)

// MTLS is the TLS setup of the TCP listener: the agent's own cert, and only
// client certificates that chain to the api_server CA (D2). It reloads the
// three files on the next handshake after one of them changes, so a rotated
// secret needs no restart.
type MTLS struct {
	CertFile, KeyFile, ClientCAFile string
	// AllowedSANs, if set, are the client identities the agent accepts: the
	// client leaf must have one of them as a DNS or URI SAN.
	AllowedSANs []string

	mu    sync.Mutex
	cfg   *tls.Config
	stamp [3]fileStamp
}

type fileStamp struct {
	mod  time.Time
	size int64
}

// Config returns the server TLS config. It fails if the files do not load.
func (m *MTLS) Config() (*tls.Config, error) {
	if _, err := m.current(); err != nil {
		return nil, err
	}
	return &tls.Config{
		MinVersion: tls.VersionTLS13,
		GetConfigForClient: func(*tls.ClientHelloInfo) (*tls.Config, error) {
			return m.current()
		},
	}, nil
}

// Credentials wraps Config for a gRPC server.
func (m *MTLS) Credentials() (credentials.TransportCredentials, error) {
	cfg, err := m.Config()
	if err != nil {
		return nil, err
	}
	return credentials.NewTLS(cfg), nil
}

// current returns the config for the files on disk. If a reload fails (for
// example a rotation is half written), it keeps the last good config.
func (m *MTLS) current() (*tls.Config, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var stamp [3]fileStamp
	for i, f := range []string{m.CertFile, m.KeyFile, m.ClientCAFile} {
		st, err := os.Stat(f)
		if err != nil {
			if m.cfg != nil {
				return m.cfg, nil
			}
			return nil, err
		}
		stamp[i] = fileStamp{mod: st.ModTime(), size: st.Size()}
	}
	if m.cfg != nil && stamp == m.stamp {
		return m.cfg, nil
	}
	cfg, err := m.load()
	if err != nil {
		if m.cfg != nil {
			return m.cfg, nil
		}
		return nil, err
	}
	m.cfg, m.stamp = cfg, stamp
	return cfg, nil
}

func (m *MTLS) load() (*tls.Config, error) {
	cert, err := tls.LoadX509KeyPair(m.CertFile, m.KeyFile)
	if err != nil {
		return nil, fmt.Errorf("load server cert: %w", err)
	}
	raw, err := os.ReadFile(m.ClientCAFile)
	if err != nil {
		return nil, fmt.Errorf("read client CA: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(raw) {
		return nil, errors.New("client CA file has no PEM certificate")
	}
	cfg := &tls.Config{
		Certificates: []tls.Certificate{cert},
		ClientAuth:   tls.RequireAndVerifyClientCert,
		ClientCAs:    pool,
		MinVersion:   tls.VersionTLS13,
		// GetConfigForClient replaces the whole config, so ALPN must be here.
		NextProtos: []string{"h2"},
	}
	if len(m.AllowedSANs) > 0 {
		allowed := slices.Clone(m.AllowedSANs)
		cfg.VerifyPeerCertificate = func(_ [][]byte, chains [][]*x509.Certificate) error {
			return checkSANs(chains, allowed)
		}
	}
	return cfg, nil
}

func checkSANs(chains [][]*x509.Certificate, allowed []string) error {
	if len(chains) == 0 || len(chains[0]) == 0 {
		return errors.New("no verified client certificate")
	}
	leaf := chains[0][0]
	for _, n := range leaf.DNSNames {
		if slices.Contains(allowed, n) {
			return nil
		}
	}
	for _, u := range leaf.URIs {
		if slices.Contains(allowed, u.String()) {
			return nil
		}
	}
	return fmt.Errorf("client certificate %q has no allowed SAN", leaf.Subject.CommonName)
}

// MTLSCredentials is MTLS without a SAN allowlist, for a gRPC server.
func MTLSCredentials(certFile, keyFile, clientCAFile string) (credentials.TransportCredentials, error) {
	return (&MTLS{CertFile: certFile, KeyFile: keyFile, ClientCAFile: clientCAFile}).Credentials()
}
