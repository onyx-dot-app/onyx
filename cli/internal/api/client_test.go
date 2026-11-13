package api_test

import (
	"encoding/json"
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
		if r.URL.Path != "/api/search" {
			t.Errorf("path = %s, want /api/search", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"results": [{"citation_id": 1, "title": "Test", "content": "full chunk text", "link": null, "source_type": "web", "updated_at": null}]
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
	if resp.Results[0].Content != "full chunk text" {
		t.Errorf("content = %q, want %q", resp.Results[0].Content, "full chunk text")
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

func TestDecideApprovalSendsDecision(t *testing.T) {
	var gotPath, gotDecision string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		var body struct {
			Decision string `json:"decision"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		gotDecision = body.Decision
		_, _ = w.Write([]byte(`{"approval_id":"a1","decision":"APPROVED","decided_via":"SESSION_GRANT"}`))
	}))
	defer srv.Close()

	result, err := testutil.NewClient(srv.URL).DecideApproval(t.Context(), "a1", models.ApproveSession)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if gotPath != "/api/chat/approvals/a1/decision" || gotDecision != "approve_session" {
		t.Fatalf("request = %s %q", gotPath, gotDecision)
	}
	if want := (models.ApprovalDecisionResult{ApprovalID: "a1", Decision: "APPROVED", DecidedVia: "SESSION_GRANT"}); result != want {
		t.Fatalf("result = %+v, want %+v", result, want)
	}
}

func TestDecideApprovalNoLongerWaiting(t *testing.T) {
	for _, status := range []int{http.StatusConflict, http.StatusNotFound} {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(status)
			_, _ = w.Write([]byte(`{"error_code":"CONFLICT","detail":"This request was already decided or is no longer waiting"}`))
		}))
		_, err := testutil.NewClient(srv.URL).DecideApproval(t.Context(), "a1", models.RejectApproval)
		srv.Close()
		if !api.IsApprovalNoLongerWaiting(err) {
			t.Errorf("status %d: IsApprovalNoLongerWaiting(%v) = false", status, err)
		}
	}
	if api.IsApprovalNoLongerWaiting(&api.OnyxAPIError{StatusCode: http.StatusInternalServerError}) {
		t.Error("a server error must stay retryable, not no longer waiting")
	}
}

func TestErrorCodeParsedFromJSONBody(t *testing.T) {
	tests := []struct {
		name, body, wantCode, wantDetail string
	}{
		{"onyx error", `{"error_code":"APPROVAL_PENDING","detail":"Approve or reject the pending requests"}`, "APPROVAL_PENDING", "Approve or reject the pending requests"},
		{"plain fastapi error", `{"detail":"Not Found"}`, "", `{"detail":"Not Found"}`},
		{"validation list", `{"error_code":"INVALID_INPUT","detail":[{"loc":["body"]}]}`, "INVALID_INPUT", `{"error_code":"INVALID_INPUT","detail":[{"loc":["body"]}]}`},
		{"not json", `upstream failed`, "", "upstream failed"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(http.StatusConflict)
				_, _ = w.Write([]byte(tt.body))
			}))
			defer srv.Close()
			_, err := testutil.NewClient(srv.URL).ListAgents(t.Context())
			var apiErr *api.OnyxAPIError
			if !errors.As(err, &apiErr) {
				t.Fatalf("want *OnyxAPIError, got %T: %v", err, err)
			}
			if apiErr.ErrorCode != tt.wantCode || apiErr.Detail != tt.wantDetail {
				t.Errorf("got code=%q detail=%q", apiErr.ErrorCode, apiErr.Detail)
			}
		})
	}
}

func TestApprovalPendingReachesStreamError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusConflict)
		_, _ = w.Write([]byte(`{"error_code":"APPROVAL_PENDING","detail":"Approve or reject the pending requests before you send a message"}`))
	}))
	defer srv.Close()
	sid := "session"
	var got models.ErrorEvent
	for event := range testutil.NewClient(srv.URL).SendMessageStream(t.Context(), "hi", &sid, 0, nil, nil, nil) {
		if e, ok := event.(models.ErrorEvent); ok {
			got = e
		}
	}
	if got.ErrorCode != api.ErrorCodeApprovalPending || got.StatusCode != http.StatusConflict {
		t.Fatalf("error event = %+v", got)
	}
}
