package client

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

// newCountingServer answers with statuses in order, repeating the last one,
// and reports how many requests it received.
func newCountingServer(t *testing.T, statuses ...int) (*Client, *int) {
	t.Helper()
	attempts := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		status := statuses[len(statuses)-1]
		if attempts < len(statuses) {
			status = statuses[attempts]
		}
		attempts++
		body := `{}`
		if r.Method == http.MethodGet {
			body = `[]`
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
	t.Cleanup(server.Close)
	return newFastRetryClient(server.URL), &attempts
}

func TestRetriesServerErrorsOnReads(t *testing.T) {
	c, attempts := newCountingServer(t, http.StatusBadGateway, http.StatusBadGateway, http.StatusOK)
	if _, err := c.ListAPIKeys(context.Background()); err != nil {
		t.Fatalf("a read should survive transient 5xx: %v", err)
	}
	if *attempts != 3 {
		t.Errorf("got %d attempts, want 3", *attempts)
	}
}

func TestNeverReplaysPostOnServerError(t *testing.T) {
	c, attempts := newCountingServer(t, http.StatusBadGateway, http.StatusOK)
	_, err := c.CreateAPIKey(context.Background(), APIKeyArgs{Role: "basic"})
	if err == nil {
		t.Fatal("a failed POST must surface, not be replayed")
	}
	// Replaying a POST could create a second object server-side.
	if *attempts != 1 {
		t.Errorf("got %d attempts, want 1", *attempts)
	}
	if apiErr, ok := err.(*APIError); !ok || apiErr.StatusCode != http.StatusBadGateway {
		t.Errorf("the server status must survive the retry layer, got %v", err)
	}
}

func TestRetriesRateLimitsOnWrites(t *testing.T) {
	c, attempts := newCountingServer(t, http.StatusTooManyRequests, http.StatusOK)
	// A 429 is rejected before the handler runs, so replaying is safe.
	if _, err := c.CreateAPIKey(context.Background(), APIKeyArgs{Role: "basic"}); err != nil {
		t.Fatalf("a rate-limited POST should be retried: %v", err)
	}
	if *attempts != 2 {
		t.Errorf("got %d attempts, want 2", *attempts)
	}
}

func TestUserAgentIsVersioned(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `[]`)
	if _, err := c.ListAPIKeys(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := captured.Header.Get("User-Agent"); got != "terraform-provider-onyx/dev" {
		t.Errorf("User-Agent = %q, want terraform-provider-onyx/dev", got)
	}

	versioned := NewClient(Config{ServerURL: "http://example.invalid", Version: "1.2.3"})
	if versioned.userAgent != "terraform-provider-onyx/1.2.3" {
		t.Errorf("User-Agent = %q, want terraform-provider-onyx/1.2.3", versioned.userAgent)
	}
}

func TestAPIErrorMessageShape(t *testing.T) {
	// The ValueError handler answers {"message": ...} with no detail field.
	c, _ := newTestServer(t, http.StatusBadRequest, `{"message": "Credential is tied to a connector"}`)
	err := c.DeleteCredential(context.Background(), 12)
	apiErr, ok := err.(*APIError)
	if !ok {
		t.Fatalf("expected *APIError, got %T", err)
	}
	if apiErr.Detail != "Credential is tied to a connector" {
		t.Errorf("unexpected APIError: %+v", apiErr)
	}
}

func TestAPIErrorValidationShape(t *testing.T) {
	// 422s answer {"status_code", "message", "data"}.
	c, _ := newTestServer(t, http.StatusUnprocessableEntity,
		`{"status_code": 422, "message": "1 validation error for ConnectorUpdateRequest", "data": null}`)
	err := c.DeleteCredential(context.Background(), 12)
	apiErr, ok := err.(*APIError)
	if !ok {
		t.Fatalf("expected *APIError, got %T", err)
	}
	if apiErr.Detail != "1 validation error for ConnectorUpdateRequest" {
		t.Errorf("unexpected APIError: %+v", apiErr)
	}
}
