package api

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

func idleTestClient(serverURL string, idle time.Duration) *Client {
	client := NewClient(config.OnyxCliConfig{ServerURL: serverURL, APIKey: "test-key"})
	client.streamIdleTimeout = idle
	return client
}

func collectEvents(t *testing.T, events <-chan models.StreamEvent) []models.StreamEvent {
	t.Helper()
	var got []models.StreamEvent
	deadline := time.After(5 * time.Second)
	for {
		select {
		case event, ok := <-events:
			if !ok {
				return got
			}
			got = append(got, event)
		case <-deadline:
			t.Fatal("stream did not close")
		}
	}
}

func TestStreamOutlivesIdleTimeoutWhileDataArrives(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Heartbeats keep a long turn without output alive.
		for range 40 {
			fmt.Fprintln(w, `{"placement":{"turn_index":0},"obj":{"type":"chat_heartbeat"}}`)
			w.(http.Flusher).Flush()
			time.Sleep(10 * time.Millisecond)
		}
		fmt.Fprintln(w, `{"placement":{"turn_index":0},"obj":{"type":"stop"}}`)
	}))
	defer server.Close()

	// The heartbeats span twice the idle timeout, with gaps far below it.
	events := collectEvents(t, idleTestClient(server.URL, 200*time.Millisecond).SendMessageStream(t.Context(), "hi", nil, 0, nil, nil, nil))
	for _, event := range events {
		if e, ok := event.(models.ErrorEvent); ok {
			t.Fatalf("stream with steady data failed: %s", e.Error)
		}
	}
	if _, ok := events[len(events)-1].(models.StopEvent); !ok {
		t.Fatalf("last event = %T, want StopEvent", events[len(events)-1])
	}
}

func TestStreamFailsWhenServerGoesSilent(t *testing.T) {
	for name, beforeSilence := range map[string]http.HandlerFunc{
		"before headers": func(w http.ResponseWriter, r *http.Request) {},
		"mid stream": func(w http.ResponseWriter, r *http.Request) {
			fmt.Fprintln(w, `{"placement":{"turn_index":0},"obj":{"type":"message_delta","content":"hi"}}`)
			w.(http.Flusher).Flush()
		},
	} {
		t.Run(name, func(t *testing.T) {
			release := make(chan struct{})
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				beforeSilence(w, r)
				<-release
			}))
			defer server.Close()
			defer close(release)

			events := collectEvents(t, idleTestClient(server.URL, 100*time.Millisecond).SendMessageStream(t.Context(), "hi", nil, 0, nil, nil, nil))
			last, ok := events[len(events)-1].(models.ErrorEvent)
			if !ok {
				t.Fatalf("last event = %T, want ErrorEvent", events[len(events)-1])
			}
			if last.StatusCode != http.StatusRequestTimeout || !last.IsRetryable {
				t.Fatalf("idle error = %+v, want retryable 408", last)
			}
		})
	}
}

func TestStreamFailsWhenAnErrorBodyStalls(t *testing.T) {
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
		fmt.Fprint(w, `{"detail":"upstream`)
		w.(http.Flusher).Flush()
		<-release
	}))
	defer server.Close()
	defer close(release)

	events := collectEvents(t, idleTestClient(server.URL, 100*time.Millisecond).SendMessageStream(t.Context(), "hi", nil, 0, nil, nil, nil))
	if len(events) != 1 {
		t.Fatalf("events = %#v, want one error", events)
	}
	if e, ok := events[0].(models.ErrorEvent); !ok || e.StatusCode != http.StatusBadGateway {
		t.Fatalf("event = %#v, want the 502 error", events[0])
	}
}

func TestResumeReplaysTheRunningResponse(t *testing.T) {
	var path string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path = r.URL.RequestURI()
		fmt.Fprintln(w, `{"jsonrpc":"2.0","method":"_onyx/message_ids","params":{"sessionId":"session-1","packet":{"user_message_id":1,"reserved_assistant_message_id":2}}}`)
		fmt.Fprintln(w, `{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"session-1","update":{"_meta":{"onyx":{"placement":{"turn_index":0},"packet":{"type":"tool_approval_request","approval_id":"a1","tool_name":"lookup"}}},"sessionUpdate":"tool_call_update","toolCallId":"r/tool/c","status":"pending"}}}`)
		fmt.Fprintln(w, `{"jsonrpc":"2.0","method":"_onyx/stream_cursor","params":{"sessionId":"session-1","packet":{"stream_id":2,"next_cursor":1,"replay_complete":true}}}`)
		fmt.Fprintln(w, `{"jsonrpc":"2.0","method":"_onyx/stop","params":{"sessionId":"session-1","packet":{"placement":{"turn_index":0},"obj":{"type":"stop"}}}}`)
		fmt.Fprintln(w, `{"jsonrpc":"2.0","method":"_onyx/stream_cursor","params":{"sessionId":"session-1","packet":{"stream_id":2,"next_cursor":2,"replay_complete":true}}}`)
	}))
	defer server.Close()

	events := collectEvents(t, idleTestClient(server.URL, time.Second).ResumeChatStream(t.Context(), "session-1", nil, 0))

	if path != "/api/chat/chat-session/session-1/resume-stream?cursor=0&protocol_version=2" {
		t.Fatalf("path = %q", path)
	}
	if _, ok := events[1].(models.ToolApprovalRequestEvent); !ok {
		t.Fatalf("events = %#v", events)
	}
	if _, ok := events[len(events)-2].(models.StopEvent); !ok {
		t.Fatalf("event = %T, want StopEvent", events[len(events)-2])
	}
}

func TestResumeFromCursorDropsTheCutBatch(t *testing.T) {
	var path string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path = r.URL.RequestURI()
		fmt.Fprintln(w, `{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"session-1","update":{"_meta":{"onyx":{"placement":{"turn_index":0}}},"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"kept"}}}}`)
		fmt.Fprintln(w, `{"jsonrpc":"2.0","method":"_onyx/stream_cursor","params":{"sessionId":"session-1","packet":{"stream_id":7,"next_cursor":4,"replay_complete":true}}}`)
		// The connection ends inside the next batch.
		fmt.Fprintln(w, `{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"session-1","update":{"_meta":{"onyx":{"placement":{"turn_index":0}}},"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"cut"}}}}`)
	}))
	defer server.Close()

	streamID := 7
	events := collectEvents(t, idleTestClient(server.URL, time.Second).ResumeChatStream(t.Context(), "session-1", &streamID, 3))

	if path != "/api/chat/chat-session/session-1/resume-stream?cursor=3&protocol_version=2&stream_id=7" {
		t.Fatalf("path = %q", path)
	}
	if len(events) != 2 {
		t.Fatalf("events = %#v, want the complete batch only", events)
	}
	if e, ok := events[0].(models.MessageDeltaEvent); !ok || e.Content != "kept" {
		t.Fatalf("events = %#v", events)
	}
	if e, ok := events[1].(models.StreamCursorEvent); !ok || e.NextCursor != 4 {
		t.Fatalf("events = %#v", events)
	}
}

func TestResumeReportsOnlyA404AsUnavailable(t *testing.T) {
	for status, want := range map[int][]models.StreamEvent{
		http.StatusNotFound: {models.StreamUnavailableEvent{}},
		// A clean end before the first cursor leaves the response resumable.
		http.StatusOK: nil,
	} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if status == http.StatusNotFound {
				http.Error(w, `{"detail":"No resumable stream"}`, status)
			}
		}))
		events := collectEvents(t, idleTestClient(server.URL, time.Second).ResumeChatStream(t.Context(), "session-1", nil, 0))
		server.Close()
		if len(events) != len(want) || (len(want) > 0 && events[0] != want[0]) {
			t.Fatalf("HTTP %d: events = %#v, want %#v", status, events, want)
		}
	}
}
