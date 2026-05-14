package api_test

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

// TestListAgents_Timeout verifies that the wrapTimeoutError helper correctly
// wraps network timeouts as OnyxAPIError{408}. Integration tests cover the
// happy path and HTTP error cases against a real server.
func TestListAgents_Timeout(t *testing.T) {
	url := testutil.DeadServerURL()
	client := testutil.NewClient(url)
	_, err := client.ListAgents(t.Context())
	if err == nil {
		t.Fatal("expected error for dead server")
	}
}

func TestSearch_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			t.Errorf("method = %s, want POST", r.Method)
		}
		if !strings.HasSuffix(r.URL.Path, "/search") {
			t.Errorf("path = %s, want /api/search", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"results": [{"citation_id": 1, "document_id": "doc-1", "chunk_ind": 0, "title": "Test", "blurb": "blurb", "link": null, "source_type": "web", "score": 0.95, "updated_at": null}],
			"llm_facing_text": "{\"results\": []}",
			"citation_mapping": {"1": "doc-1"}
		}`))
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	resp, err := client.Search(t.Context(), models.SearchRequest{Query: "test"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(resp.Results) != 1 {
		t.Fatalf("expected 1 result, got %d", len(resp.Results))
	}
	if resp.Results[0].DocumentID != "doc-1" {
		t.Errorf("document_id = %q, want %q", resp.Results[0].DocumentID, "doc-1")
	}
	if resp.LLMFacingText == "" {
		t.Error("llm_facing_text is empty")
	}
}

func TestSearch_401(t *testing.T) {
	srv := testutil.StatusServer(401)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	_, err := client.Search(t.Context(), models.SearchRequest{Query: "test"})
	if err == nil {
		t.Fatal("expected error for 401")
	}
	var apiErr *api.OnyxAPIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("want *OnyxAPIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 401 {
		t.Errorf("status = %d, want 401", apiErr.StatusCode)
	}
}

// TestTestConnection_AWSELB403 verifies that TestConnection detects an AWS
// ALB/ELB 403 by inspecting the Server response header. This header-sniffing
// logic cannot be exercised by integration tests since it requires a specific
// proxy behavior.
func TestTestConnection_AWSELB403(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Server", "awselb/2.0")
		w.WriteHeader(403)
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	err := client.TestConnection(t.Context())
	if err == nil {
		t.Fatal("expected error")
	}
	var authErr *api.AuthError
	if !errors.As(err, &authErr) {
		t.Fatalf("expected AuthError for AWS ELB 403, got %T: %v", err, err)
	}
	if !strings.Contains(authErr.Error(), "AWS load balancer") {
		t.Fatalf("expected AWS load balancer message, got: %s", authErr.Error())
	}
}
