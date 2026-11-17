package relay

import (
	"crypto/tls"
	"errors"
	"fmt"
	"sync"

	"github.com/onyx-dot-app/onyx/microvm/internal/tlsfiles"
)

// UpstreamTLS is the mTLS setup of the relay → proxy hop: the relay checks
// the proxy certificate against CAFile and ServerName, and shows its own
// client certificate. It reloads the files on the next connection after one
// of them changes.
type UpstreamTLS struct {
	CAFile, CertFile, KeyFile string
	// ServerName must be a DNS (or, for an IP, an IP) SAN of the proxy certificate.
	ServerName string

	once sync.Once
	r    *tlsfiles.Reloader
}

// Check loads the files once, so a bad setup stops the agent at start.
func (u *UpstreamTLS) Check() error {
	if u.CAFile == "" || u.CertFile == "" || u.KeyFile == "" || u.ServerName == "" {
		return errors.New("upstream TLS needs a CA, a client certificate, its key and a server name")
	}
	_, err := u.config()
	return err
}

func (u *UpstreamTLS) config() (*tls.Config, error) {
	u.once.Do(func() {
		u.r = &tlsfiles.Reloader{Files: []string{u.CAFile, u.CertFile, u.KeyFile}, Load: u.load}
	})
	return u.r.Current()
}

func (u *UpstreamTLS) load() (*tls.Config, error) {
	cert, err := tls.LoadX509KeyPair(u.CertFile, u.KeyFile)
	if err != nil {
		return nil, fmt.Errorf("load relay client cert: %w", err)
	}
	pool, err := tlsfiles.CertPool(u.CAFile)
	if err != nil {
		return nil, fmt.Errorf("proxy CA: %w", err)
	}
	return &tls.Config{
		RootCAs:      pool,
		Certificates: []tls.Certificate{cert},
		ServerName:   u.ServerName,
		MinVersion:   tls.VersionTLS13,
		// One full handshake per VM connection is costly for the proxy.
		ClientSessionCache: tls.NewLRUClientSessionCache(256),
	}, nil
}
