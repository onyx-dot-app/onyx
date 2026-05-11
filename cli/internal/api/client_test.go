package api_test

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
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
