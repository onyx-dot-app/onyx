package api_test

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

func TestListAgents_Success(t *testing.T) {
	agents := []models.AgentSummary{
		{ID: 1, Name: "Agent1", IsVisible: true},
		{ID: 2, Name: "Hidden", IsVisible: false},
		{ID: 3, Name: "Agent3", IsVisible: true},
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/persona" {
			w.WriteHeader(404)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(agents)
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	result, err := client.ListAgents(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(result) != 2 {
		t.Fatalf("expected 2 visible agents, got %d", len(result))
	}
	if result[0].Name != "Agent1" || result[1].Name != "Agent3" {
		t.Fatalf("unexpected agents: %+v", result)
	}
}

func TestListAgents_HTTPError(t *testing.T) {
	srv := testutil.StatusServer(500)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	_, err := client.ListAgents(context.Background())
	if err == nil {
		t.Fatal("expected error")
	}
	var apiErr *api.OnyxAPIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected OnyxAPIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 500 {
		t.Fatalf("expected status 500, got %d", apiErr.StatusCode)
	}
}

func TestListAgents_Timeout(t *testing.T) {
	url := testutil.DeadServerURL()
	client := testutil.NewClient(url)
	_, err := client.ListAgents(context.Background())
	if err == nil {
		t.Fatal("expected error for dead server")
	}
	// The error may or may not be an OnyxAPIError{408} depending on
	// whether the OS returns a timeout or connection-refused. Just verify
	// we got an error.
}

func TestTestConnection_Success(t *testing.T) {
	srv := testutil.OnyxServer(200)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	if err := client.TestConnection(context.Background()); err != nil {
		t.Fatalf("expected success, got: %v", err)
	}
}

func TestTestConnection_Auth401(t *testing.T) {
	srv := testutil.OnyxServer(401)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	err := client.TestConnection(context.Background())
	if err == nil {
		t.Fatal("expected auth error")
	}
	var authErr *api.AuthError
	if !errors.As(err, &authErr) {
		t.Fatalf("expected AuthError, got %T: %v", err, err)
	}
}

func TestTestConnection_Auth403(t *testing.T) {
	srv := testutil.OnyxServer(403)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	err := client.TestConnection(context.Background())
	if err == nil {
		t.Fatal("expected auth error")
	}
	var authErr *api.AuthError
	if !errors.As(err, &authErr) {
		t.Fatalf("expected AuthError, got %T: %v", err, err)
	}
}

func TestTestConnection_HTTPError429(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) })
	mux.HandleFunc("/api/me", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(429) })
	srv := httptest.NewServer(mux)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	err := client.TestConnection(context.Background())
	if err == nil {
		t.Fatal("expected error")
	}
	var apiErr *api.OnyxAPIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected OnyxAPIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 429 {
		t.Fatalf("expected status 429, got %d", apiErr.StatusCode)
	}
}

func TestTestConnection_HTTPError500(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) })
	mux.HandleFunc("/api/me", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(500) })
	srv := httptest.NewServer(mux)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	err := client.TestConnection(context.Background())
	if err == nil {
		t.Fatal("expected error")
	}
	var apiErr *api.OnyxAPIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected OnyxAPIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 500 {
		t.Fatalf("expected status 500, got %d", apiErr.StatusCode)
	}
}

func TestTestConnection_HTTPError504(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) })
	mux.HandleFunc("/api/me", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(504) })
	srv := httptest.NewServer(mux)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	err := client.TestConnection(context.Background())
	if err == nil {
		t.Fatal("expected error")
	}
	var apiErr *api.OnyxAPIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected OnyxAPIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 504 {
		t.Fatalf("expected status 504, got %d", apiErr.StatusCode)
	}
}

func TestTestConnection_Unreachable(t *testing.T) {
	url := testutil.DeadServerURL()
	client := testutil.NewClient(url)
	err := client.TestConnection(context.Background())
	if err == nil {
		t.Fatal("expected error for unreachable server")
	}
}

func TestTestConnection_AWSELB403(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Server", "awselb/2.0")
		w.WriteHeader(403)
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	err := client.TestConnection(context.Background())
	if err == nil {
		t.Fatal("expected error")
	}
	var authErr *api.AuthError
	if !errors.As(err, &authErr) {
		t.Fatalf("expected AuthError for AWS ELB 403, got %T: %v", err, err)
	}
	if got := authErr.Error(); !contains(got, "AWS load balancer") {
		t.Fatalf("expected AWS load balancer message, got: %s", got)
	}
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub || len(s) > 0 && containsSubstring(s, sub))
}

func containsSubstring(s, sub string) bool {
	for i := 0; i <= len(s)-len(sub); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}

func TestClientAPI_InterfaceCompiles(t *testing.T) {
	// This test just verifies the interface is satisfied at compile time.
	// The actual compile-time check is in client.go via: var _ ClientAPI = (*Client)(nil)
	srv := testutil.OnyxServer(200)
	defer srv.Close()
	var _ api.ClientAPI = testutil.NewClient(srv.URL) //nolint:staticcheck // compile-time interface check
}
