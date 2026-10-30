package api_test

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

func TestCancellationWaitsForAcknowledgement(t *testing.T) {
	started := make(chan struct{})
	acknowledge := make(chan struct{})
	stopped := make(chan string, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/chat/stop-chat-session/session" {
			stopped <- r.URL.Query().Get("stream_id")
			return
		}
		fmt.Fprintln(w, `{"chat_session_id":"session"}`)
		w.(http.Flusher).Flush()
		close(started)
		<-acknowledge
		fmt.Fprintln(w, `{"user_message_id":10,"reserved_assistant_message_id":11}`)
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	}))
	defer server.Close()
	client := testutil.NewClient(server.URL)
	ctx, cancel := context.WithCancel(t.Context())
	events := client.SendMessageStream(ctx, "hello", nil, 0, nil, nil, nil)
	<-started
	cancel()
	select {
	case <-stopped:
		t.Fatal("Stop sent before acknowledgement")
	case <-time.After(20 * time.Millisecond):
	}
	close(acknowledge)
	select {
	case id := <-stopped:
		if id != "11" {
			t.Fatalf("Stop id = %s", id)
		}
	case <-time.After(time.Second):
		t.Fatal("no scoped Stop")
	}
	for range events {
	}
}

func TestReadinessFailsClosed(t *testing.T) {
	for _, body := range []string{`{}`, `{"is_processing":true}`, `{"is_processing":"false"}`} {
		t.Run(body, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, body) }))
			defer server.Close()
			processing, err := testutil.NewClient(server.URL).IsChatSessionProcessing(t.Context(), "session")
			if !processing {
				t.Fatalf("unconfirmed response declared idle: %s (%v)", body, err)
			}
		})
	}
}

func TestIdleWaitHonorsCancellation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, `{"is_processing":true}`) }))
	defer server.Close()
	ctx, cancel := context.WithTimeout(t.Context(), 20*time.Millisecond)
	defer cancel()
	if err := api.WaitForChatSessionIdle(ctx, testutil.NewClient(server.URL), "session"); err == nil {
		t.Fatal("busy session declared idle")
	}
}

func TestCancellationWithoutAcknowledgementIsBounded(t *testing.T) {
	started := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.(http.Flusher).Flush()
		close(started)
		<-r.Context().Done()
	}))
	defer server.Close()
	ctx, cancel := context.WithCancel(t.Context())
	events := testutil.NewClient(server.URL).SendMessageStream(ctx, "hello", nil, 0, nil, []models.FileDescriptorPayload{}, nil)
	<-started
	cancel()
	done := make(chan struct{})
	go func() {
		for range events {
		}
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(12 * time.Second):
		t.Fatal("cancelled stream did not close")
	}
}

func TestCancellationAtDeliveryEndStillStopsAcknowledgedRun(t *testing.T) {
	for range 30 {
		ctx, cancel := context.WithCancel(t.Context())
		stopped := make(chan string, 1)
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/api/chat/stop-chat-session/session" {
				stopped <- r.URL.Query().Get("stream_id")
				return
			}
			fmt.Fprintln(w, `{"chat_session_id":"session"}`)
			fmt.Fprintln(w, `{"user_message_id":10,"reserved_assistant_message_id":11}`)
			cancel()
		}))
		events := testutil.NewClient(server.URL).SendMessageStream(ctx, "hello", nil, 0, nil, nil, nil)
		var sessionID string
		var responseID int
		for event := range events {
			switch e := event.(type) {
			case models.SessionCreatedEvent:
				sessionID = e.ChatSessionID
			case models.MessageIDEvent:
				responseID = e.ReservedAgentMessageID
			}
		}
		if sessionID != "session" || responseID != 11 {
			server.Close()
			t.Fatalf("cancelled turn lost identity: session=%q response=%d", sessionID, responseID)
		}
		select {
		case id := <-stopped:
			if id != "11" {
				t.Fatalf("wrong Stop id %q", id)
			}
		case <-time.After(time.Second):
			server.Close()
			t.Fatal("delivery end discarded acknowledged cancellation")
		}
		server.Close()
	}
}

func TestCancelledDeliveryWaitsForStopRequest(t *testing.T) {
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	stopStarted := make(chan struct{})
	releaseStop := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/chat/stop-chat-session/session" {
			close(stopStarted)
			<-releaseStop
			return
		}
		fmt.Fprintln(w, `{"chat_session_id":"session"}`)
		fmt.Fprintln(w, `{"user_message_id":10,"reserved_assistant_message_id":11}`)
		cancel()
	}))
	defer server.Close()
	events := testutil.NewClient(server.URL).SendMessageStream(ctx, "hello", nil, 0, nil, nil, nil)
	deliveryDone := make(chan struct{})
	defer func() {
		close(releaseStop)
		select {
		case <-deliveryDone:
		case <-time.After(time.Second):
			t.Error("delivery did not close after Stop completed")
		}
	}()
	go func() {
		for range events {
		}
		close(deliveryDone)
	}()
	select {
	case <-stopStarted:
	case <-time.After(time.Second):
		t.Fatal("Stop request did not start")
	}
	select {
	case <-deliveryDone:
		t.Fatal("delivery closed before Stop completed; the CLI can exit without cancelling the run")
	case <-time.After(20 * time.Millisecond):
	}
}

func TestIdleWaitRetriesTransientFailures(t *testing.T) {
	for _, status := range []int{http.StatusRequestTimeout, http.StatusTooManyRequests, http.StatusServiceUnavailable} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if calls == 1 {
					w.WriteHeader(status)
					return
				}
				fmt.Fprint(w, `{"is_processing":false}`)
			}))
			defer server.Close()
			ctx, cancel := context.WithTimeout(t.Context(), 3*time.Second)
			defer cancel()
			if err := api.WaitForChatSessionIdle(ctx, testutil.NewClient(server.URL), "session"); err != nil {
				t.Fatal(err)
			}
			if calls != 2 {
				t.Fatalf("requests = %d, want 2", calls)
			}
		})
	}
}

func TestIdleWaitRejectsUnsupportedReadinessEndpoint(t *testing.T) {
	for _, status := range []int{http.StatusNotFound, http.StatusMethodNotAllowed} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls++; w.WriteHeader(status) }))
			defer server.Close()
			err := api.WaitForChatSessionIdle(t.Context(), testutil.NewClient(server.URL), "session")
			var apiErr *api.OnyxAPIError
			if !errors.As(err, &apiErr) || apiErr.StatusCode != status || !strings.Contains(err.Error(), "readiness endpoint unavailable") {
				t.Fatalf("unexpected error: %v", err)
			}
			if calls != 1 {
				t.Fatalf("unsupported endpoint retried %d times", calls)
			}
		})
	}
}
