package api_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
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

// --- ListChatSessions tests ---

func TestListChatSessions_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/chat/get-user-chat-sessions" {
			w.WriteHeader(404)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"sessions": [{"id": "s1", "name": "Test", "persona_id": 1, "time_created": "2025-01-01", "time_updated": "2025-01-02"}]}`)
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	sessions, err := client.ListChatSessions(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(sessions) != 1 {
		t.Fatalf("expected 1 session, got %d", len(sessions))
	}
	if sessions[0].ID != "s1" {
		t.Fatalf("expected session ID 's1', got %q", sessions[0].ID)
	}
	if sessions[0].Name == nil || *sessions[0].Name != "Test" {
		t.Fatalf("expected session name 'Test', got %v", sessions[0].Name)
	}
}

func TestListChatSessions_HTTPError(t *testing.T) {
	srv := testutil.StatusServer(500)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	_, err := client.ListChatSessions(context.Background())
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

// --- GetChatSession tests ---

func TestGetChatSession_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/chat/get-chat-session/s1" {
			w.WriteHeader(404)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{
			"chat_session_id": "s1",
			"description": "A test session",
			"persona_id": 1,
			"persona_name": "TestAgent",
			"messages": [
				{
					"message_id": 1,
					"parent_message": null,
					"latest_child_message": 2,
					"message": "Hello",
					"message_type": "user",
					"time_sent": "2025-01-01T00:00:00Z",
					"error": null
				}
			]
		}`)
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	resp, err := client.GetChatSession(context.Background(), "s1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.ChatSessionID != "s1" {
		t.Fatalf("expected session ID 's1', got %q", resp.ChatSessionID)
	}
	if resp.AgentName == nil || *resp.AgentName != "TestAgent" {
		t.Fatalf("expected agent name 'TestAgent', got %v", resp.AgentName)
	}
	if len(resp.Messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(resp.Messages))
	}
	if resp.Messages[0].Message != "Hello" {
		t.Fatalf("expected message 'Hello', got %q", resp.Messages[0].Message)
	}
}

func TestGetChatSession_HTTPError(t *testing.T) {
	srv := testutil.StatusServer(500)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	_, err := client.GetChatSession(context.Background(), "s1")
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

// --- RenameChatSession tests ---

func TestRenameChatSession_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/chat/rename-chat-session" || r.Method != http.MethodPut {
			w.WriteHeader(404)
			return
		}
		var payload map[string]any
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			w.WriteHeader(400)
			return
		}
		if payload["chat_session_id"] != "s1" {
			w.WriteHeader(400)
			fmt.Fprint(w, `{"detail":"wrong session id"}`)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"new_name": "renamed"}`)
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	name := "renamed"
	newName, err := client.RenameChatSession(context.Background(), "s1", &name)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if newName != "renamed" {
		t.Fatalf("expected new name 'renamed', got %q", newName)
	}
}

func TestRenameChatSession_HTTPError(t *testing.T) {
	srv := testutil.StatusServer(500)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	name := "new-name"
	_, err := client.RenameChatSession(context.Background(), "s1", &name)
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

// --- GetBackendVersion tests ---

func TestGetBackendVersion_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/version" {
			w.WriteHeader(404)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"backend_version": "1.2.3"}`)
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	version, err := client.GetBackendVersion(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if version != "1.2.3" {
		t.Fatalf("expected version '1.2.3', got %q", version)
	}
}

func TestGetBackendVersion_HTTPError(t *testing.T) {
	srv := testutil.StatusServer(500)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	_, err := client.GetBackendVersion(context.Background())
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

// --- UploadFile tests ---

func TestUploadFile_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/user/projects/file/upload" || r.Method != http.MethodPost {
			w.WriteHeader(404)
			return
		}
		ct := r.Header.Get("Content-Type")
		if !contains(ct, "multipart/form-data") {
			t.Errorf("expected multipart/form-data content type, got %q", ct)
			w.WriteHeader(400)
			return
		}
		if err := r.ParseMultipartForm(10 << 20); err != nil {
			t.Errorf("failed to parse multipart form: %v", err)
			w.WriteHeader(400)
			return
		}
		file, header, err := r.FormFile("files")
		if err != nil {
			t.Errorf("failed to get form file: %v", err)
			w.WriteHeader(400)
			return
		}
		defer func() { _ = file.Close() }()
		if header.Filename != "test-upload.txt" {
			t.Errorf("expected filename 'test-upload.txt', got %q", header.Filename)
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"user_files": [{"id": "uf1", "name": "test-upload.txt", "file_id": "f123", "chat_file_type": "plain_text"}]}`)
	}))
	defer srv.Close()

	tmpDir := t.TempDir()
	tmpFile := filepath.Join(tmpDir, "test-upload.txt")
	if err := os.WriteFile(tmpFile, []byte("hello world"), 0o644); err != nil {
		t.Fatalf("failed to create temp file: %v", err)
	}

	client := testutil.NewClient(srv.URL)
	desc, err := client.UploadFile(context.Background(), tmpFile)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if desc.ID != "f123" {
		t.Fatalf("expected file ID 'f123', got %q", desc.ID)
	}
	if desc.Type != models.ChatFilePlainText {
		t.Fatalf("expected type 'plain_text', got %q", desc.Type)
	}
	if desc.Name != "test-upload.txt" {
		t.Fatalf("expected name 'test-upload.txt', got %q", desc.Name)
	}
}

func TestUploadFile_HTTPError(t *testing.T) {
	srv := testutil.StatusServer(500)
	defer srv.Close()

	tmpDir := t.TempDir()
	tmpFile := filepath.Join(tmpDir, "test-upload.txt")
	if err := os.WriteFile(tmpFile, []byte("hello"), 0o644); err != nil {
		t.Fatalf("failed to create temp file: %v", err)
	}

	client := testutil.NewClient(srv.URL)
	_, err := client.UploadFile(context.Background(), tmpFile)
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

func TestClientAPI_InterfaceCompiles(t *testing.T) {
	// This test just verifies the interface is satisfied at compile time.
	// The actual compile-time check is in client.go via: var _ ClientAPI = (*Client)(nil)
	srv := testutil.OnyxServer(200)
	defer srv.Close()
	var _ api.ClientAPI = testutil.NewClient(srv.URL) //nolint:staticcheck // compile-time interface check
}
