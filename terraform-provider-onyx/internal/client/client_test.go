package client

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

// capturedRequest records what the test server received.
type capturedRequest struct {
	Method string
	Path   string // includes query string
	Header http.Header
	Body   []byte
}

// newTestServer returns a client pointed at an httptest server that replies
// with status and responseBody, capturing the last request.
func newTestServer(t *testing.T, status int, responseBody string) (*Client, *capturedRequest) {
	t.Helper()
	captured := &capturedRequest{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		captured.Method = r.Method
		captured.Path = r.URL.RequestURI()
		captured.Header = r.Header.Clone()
		captured.Body, _ = io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(responseBody))
	}))
	t.Cleanup(server.Close)
	return NewClient(server.URL, "", "on_test_key"), captured
}

func bodyAsMap(t *testing.T, body []byte) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(body, &m); err != nil {
		t.Fatalf("request body is not JSON: %v\nbody: %s", err, body)
	}
	return m
}

func TestNewClientBaseURL(t *testing.T) {
	tests := []struct {
		serverURL string
		apiPrefix string
		want      string
	}{
		{"http://localhost:3000", "/api", "http://localhost:3000/api"},
		{"http://localhost:3000/", "/api", "http://localhost:3000/api"},
		{"http://localhost:8080", "", "http://localhost:8080"},
		{"https://cloud.onyx.app/", "api", "https://cloud.onyx.app/api"},
	}
	for _, tt := range tests {
		if got := NewClient(tt.serverURL, tt.apiPrefix, "k").BaseURL(); got != tt.want {
			t.Errorf("NewClient(%q, %q): base URL = %q, want %q", tt.serverURL, tt.apiPrefix, got, tt.want)
		}
	}
}

func TestAuthHeaders(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `[]`)
	if _, err := c.ListAPIKeys(context.Background()); err != nil {
		t.Fatal(err)
	}
	want := "Bearer on_test_key"
	if got := captured.Header.Get("Authorization"); got != want {
		t.Errorf("Authorization = %q, want %q", got, want)
	}
	if got := captured.Header.Get("X-Onyx-Authorization"); got != want {
		t.Errorf("X-Onyx-Authorization = %q, want %q", got, want)
	}
}

func TestAPIErrorParsing(t *testing.T) {
	c, _ := newTestServer(t, http.StatusNotFound, `{"error_code": "NOT_FOUND", "detail": "Session not found"}`)
	err := c.DeleteAPIKey(context.Background(), 42)
	if err == nil {
		t.Fatal("expected error")
	}
	apiErr, ok := err.(*APIError)
	if !ok {
		t.Fatalf("expected *APIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != http.StatusNotFound || apiErr.ErrorCode != "NOT_FOUND" || apiErr.Detail != "Session not found" {
		t.Errorf("unexpected APIError: %+v", apiErr)
	}
	if !IsNotFound(err) {
		t.Error("IsNotFound should be true for a 404 APIError")
	}
}

func TestAPIErrorHTMLResponse(t *testing.T) {
	c, _ := newTestServer(t, http.StatusBadGateway, `<!DOCTYPE html><html><body>oops</body></html>`)
	err := c.DeleteAPIKey(context.Background(), 42)
	apiErr, ok := err.(*APIError)
	if !ok {
		t.Fatalf("expected *APIError, got %T", err)
	}
	if apiErr.ErrorCode != "" || apiErr.StatusCode != http.StatusBadGateway {
		t.Errorf("unexpected APIError: %+v", apiErr)
	}
	if IsNotFound(err) {
		t.Error("IsNotFound should be false for a 502")
	}
}

func TestAPIErrorNonStringDetail(t *testing.T) {
	// FastAPI validation errors return detail as a structured list.
	c, _ := newTestServer(t, http.StatusUnprocessableEntity, `{"detail": [{"loc": ["body", "role"], "msg": "invalid"}]}`)
	err := c.DeleteAPIKey(context.Background(), 42)
	apiErr, ok := err.(*APIError)
	if !ok {
		t.Fatalf("expected *APIError, got %T", err)
	}
	if apiErr.Detail == "" {
		t.Error("Detail should carry the raw JSON for structured validation errors")
	}
}
