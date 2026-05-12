package testutil

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
)

// NewClient creates a test API client pointed at the given URL.
func NewClient(url string) *api.Client {
	return api.NewClient(config.OnyxCliConfig{ServerURL: url, APIKey: "test-key"})
}

// StatusServer returns an httptest.Server that always responds with the given status code.
func StatusServer(status int) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
	}))
}

// OnyxServer returns an httptest.Server that simulates the Onyx backend.
func OnyxServer(meStatus int) *httptest.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/me", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(meStatus)
		if meStatus == 200 {
			fmt.Fprint(w, `{"id":1}`)
		}
	})
	mux.HandleFunc("/api/version", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]string{"backend_version": "0.1.0"})
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
	})
	return httptest.NewServer(mux)
}

// DeadServerURL returns a URL whose server has already been closed.
func DeadServerURL() string {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	url := srv.URL
	srv.Close()
	return url
}

// IsolateConfig sets env vars so tests use a temp config directory.
func IsolateConfig(t *testing.T, serverURL string) {
	t.Helper()
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("ONYX_SERVER_URL", serverURL)
	t.Setenv("ONYX_PAT", "test-key")
}

// TestIOStreams returns an IOStreams backed by buffers for testing.
func TestIOStreams() (*iostreams.IOStreams, *bytes.Buffer, *bytes.Buffer) {
	out := &bytes.Buffer{}
	errOut := &bytes.Buffer{}
	return &iostreams.IOStreams{In: &bytes.Buffer{}, Out: out, ErrOut: errOut}, out, errOut
}
