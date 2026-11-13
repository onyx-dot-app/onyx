package metrics

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func scrape(t *testing.T, h http.Handler, header string) int {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	if header != "" {
		req.Header.Set("Authorization", header)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code == http.StatusUnauthorized && rec.Header().Get("WWW-Authenticate") != "Bearer" {
		t.Fatalf("401 without WWW-Authenticate: Bearer")
	}
	return rec.Code
}

var ok = http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })

func TestBearerAuth(t *testing.T) {
	file := filepath.Join(t.TempDir(), "token")
	if err := os.WriteFile(file, []byte("s3cret\n"), 0o400); err != nil {
		t.Fatal(err)
	}
	h := BearerAuth{TokenFile: file}.Wrap(ok)
	for name, tc := range map[string]struct {
		header string
		code   int
	}{
		"missing":      {"", http.StatusUnauthorized},
		"wrong":        {"Bearer nope", http.StatusUnauthorized},
		"prefix only":  {"Bearer ", http.StatusUnauthorized},
		"other scheme": {"Basic s3cret", http.StatusUnauthorized},
		"right":        {"Bearer s3cret", http.StatusOK},
	} {
		if got := scrape(t, h, tc.header); got != tc.code {
			t.Errorf("%s: got %d, want %d", name, got, tc.code)
		}
	}
}

func TestBearerAuthFailsClosed(t *testing.T) {
	empty := filepath.Join(t.TempDir(), "empty")
	if err := os.WriteFile(empty, []byte("\n"), 0o400); err != nil {
		t.Fatal(err)
	}
	for name, a := range map[string]BearerAuth{
		"no token file": {},
		"missing file":  {TokenFile: filepath.Join(t.TempDir(), "absent")},
		"empty token":   {TokenFile: empty},
	} {
		if got := scrape(t, a.Wrap(ok), "Bearer "); got != http.StatusUnauthorized {
			t.Errorf("%s: got %d", name, got)
		}
		if got := scrape(t, a.Wrap(ok), "Bearer x"); got != http.StatusUnauthorized {
			t.Errorf("%s: got %d", name, got)
		}
	}
	if got := scrape(t, BearerAuth{Disabled: true}.Wrap(ok), ""); got != http.StatusOK {
		t.Errorf("disabled: got %d", got)
	}
}

// A Secret volume update swaps the file; the next scrape uses the new token.
func TestBearerAuthReloadsToken(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "token")
	if err := os.WriteFile(file, []byte("old"), 0o600); err != nil {
		t.Fatal(err)
	}
	h := BearerAuth{TokenFile: file}.Wrap(ok)
	if got := scrape(t, h, "Bearer old"); got != http.StatusOK {
		t.Fatalf("old token: %d", got)
	}
	next := filepath.Join(dir, "token.new")
	if err := os.WriteFile(next, []byte("new"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(next, file); err != nil {
		t.Fatal(err)
	}
	if got := scrape(t, h, "Bearer old"); got != http.StatusUnauthorized {
		t.Errorf("old token after rotation: %d", got)
	}
	if got := scrape(t, h, "Bearer new"); got != http.StatusOK {
		t.Errorf("new token after rotation: %d", got)
	}
}
