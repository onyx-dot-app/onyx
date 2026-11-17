package metrics

import (
	"bytes"
	"crypto/subtle"
	"io"
	"net/http"
	"os"
	"strings"
)

// maxTokenBytes bounds the token file read.
const maxTokenBytes = 4096

const bearerPrefix = "Bearer "

// BearerAuth guards /metrics like the api_server's METRICS_AUTH_TOKEN check
// (backend/onyx/server/metrics/metrics_auth.py): it fails closed. With no
// token and not Disabled, every scrape gets 401.
type BearerAuth struct {
	// TokenFile is read on every request, so a rotated Secret volume applies
	// without a restart.
	TokenFile string
	Disabled  bool
}

func (a BearerAuth) token() []byte {
	if a.TokenFile == "" {
		return nil
	}
	f, err := os.Open(a.TokenFile)
	if err != nil {
		return nil
	}
	defer func() { _ = f.Close() }()
	b, err := io.ReadAll(io.LimitReader(f, maxTokenBytes+1))
	if err != nil || len(b) > maxTokenBytes {
		return nil
	}
	return bytes.TrimSpace(b)
}

// Wrap returns h behind the bearer token check.
func (a BearerAuth) Wrap(h http.Handler) http.Handler {
	if a.Disabled {
		return h
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		want := a.token()
		got, ok := strings.CutPrefix(r.Header.Get("Authorization"), bearerPrefix)
		if len(want) == 0 || !ok || subtle.ConstantTimeCompare([]byte(strings.TrimSpace(got)), want) != 1 {
			w.Header().Set("WWW-Authenticate", "Bearer")
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		h.ServeHTTP(w, r)
	})
}
