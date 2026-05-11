package api_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

func drainEvents(ch <-chan models.StreamEvent) []models.StreamEvent {
	var events []models.StreamEvent
	for e := range ch {
		events = append(events, e)
	}
	return events
}

func TestSendMessageStream_HTTPError(t *testing.T) {
	srv := testutil.StatusServer(500)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	ch := client.SendMessageStream(context.Background(), "hello", nil, 0, nil, nil)
	events := drainEvents(ch)
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	errEvent, ok := events[0].(models.ErrorEvent)
	if !ok {
		t.Fatalf("expected ErrorEvent, got %T", events[0])
	}
	if errEvent.StatusCode != 500 {
		t.Fatalf("expected status code 500, got %d", errEvent.StatusCode)
	}
}

func TestSendMessageStream_5xxRetryable(t *testing.T) {
	srv := testutil.StatusServer(502)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	ch := client.SendMessageStream(context.Background(), "hello", nil, 0, nil, nil)
	events := drainEvents(ch)
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	errEvent, ok := events[0].(models.ErrorEvent)
	if !ok {
		t.Fatalf("expected ErrorEvent, got %T", events[0])
	}
	if !errEvent.IsRetryable {
		t.Fatal("5xx errors should be retryable")
	}
}

func TestSendMessageStream_4xxNotRetryable(t *testing.T) {
	srv := testutil.StatusServer(400)
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	ch := client.SendMessageStream(context.Background(), "hello", nil, 0, nil, nil)
	events := drainEvents(ch)
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	errEvent, ok := events[0].(models.ErrorEvent)
	if !ok {
		t.Fatalf("expected ErrorEvent, got %T", events[0])
	}
	if errEvent.IsRetryable {
		t.Fatal("4xx errors should not be retryable")
	}
	if errEvent.StatusCode != 400 {
		t.Fatalf("expected status code 400, got %d", errEvent.StatusCode)
	}
}

func TestSendMessageStream_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(200)
		// Write NDJSON lines simulating a session creation and a message delta
		fmt.Fprintln(w, `{"session_id": "abc123"}`)
		fmt.Fprintln(w, `{"answer_piece": "Hello"}`)
		fmt.Fprintln(w, `{"answer_piece": " world"}`)
	}))
	defer srv.Close()

	client := testutil.NewClient(srv.URL)
	ch := client.SendMessageStream(context.Background(), "hello", nil, 0, nil, nil)
	events := drainEvents(ch)
	// We should get at least some events (the parser handles the specific format)
	// The key assertion is that we don't get an error event for a 200 response
	for _, e := range events {
		if errEvent, ok := e.(models.ErrorEvent); ok {
			t.Fatalf("unexpected error event: %s", errEvent.Error)
		}
	}
}

func TestSendMessageStream_ContextCancellation(t *testing.T) {
	// Server that blocks until the request is cancelled
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
		// Flush headers
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
		// Block until client disconnects
		<-r.Context().Done()
	}))
	defer srv.Close()

	ctx, cancel := context.WithCancel(context.Background())
	client := testutil.NewClient(srv.URL)
	ch := client.SendMessageStream(ctx, "hello", nil, 0, nil, nil)

	// Cancel immediately
	cancel()

	events := drainEvents(ch)
	// Should get no error events (cancellation is silent)
	for _, e := range events {
		if errEvent, ok := e.(models.ErrorEvent); ok {
			t.Fatalf("unexpected error event after cancel: %s", errEvent.Error)
		}
	}
}
