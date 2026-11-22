// Package tlsfiles keeps a TLS config in step with its PEM files, so a
// rotated Kubernetes Secret applies without a restart.
package tlsfiles

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"os"
	"slices"
	"sync"
	"time"
)

// Reloader returns the config that Load builds from Files. It calls Load
// again on the first Current after one of the files changes. If a reload
// fails (for example a rotation is half written), it keeps the last good
// config.
type Reloader struct {
	Files []string
	Load  func() (*tls.Config, error)

	mu    sync.Mutex
	cfg   *tls.Config
	stamp []fileStamp
}

type fileStamp struct {
	mod  time.Time
	size int64
}

// Current returns the config for the files on disk.
func (r *Reloader) Current() (*tls.Config, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	stamp := make([]fileStamp, len(r.Files))
	for i, f := range r.Files {
		st, err := os.Stat(f)
		if err != nil {
			if r.cfg != nil {
				return r.cfg, nil
			}
			return nil, err
		}
		stamp[i] = fileStamp{mod: st.ModTime(), size: st.Size()}
	}
	if r.cfg != nil && slices.Equal(stamp, r.stamp) {
		return r.cfg, nil
	}
	cfg, err := r.Load()
	if err != nil {
		if r.cfg != nil {
			return r.cfg, nil
		}
		return nil, err
	}
	r.cfg, r.stamp = cfg, stamp
	return cfg, nil
}

// CertPool reads a PEM CA file.
func CertPool(file string) (*x509.CertPool, error) {
	raw, err := os.ReadFile(file)
	if err != nil {
		return nil, fmt.Errorf("read CA: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(raw) {
		return nil, errors.New("CA file has no PEM certificate")
	}
	return pool, nil
}
