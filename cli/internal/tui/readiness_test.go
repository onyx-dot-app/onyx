package tui

import (
	tea "charm.land/bubbletea/v2"
	"context"
	"errors"
	"fmt"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestStreamStopWaitsForIdle(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	ch := make(chan models.StreamEvent)
	sid := "session"
	m.streamCh = ch
	m.chatSessionID = &sid
	m.isStreaming = true
	updated, cmd := m.handleStreamEvent(StreamEventMsg{Channel: ch, Event: models.StopEvent{}})
	m = updated.(Model)
	if !m.isStreaming || cmd == nil {
		t.Fatal("STOP released input before idle")
	}
	updated, cmd = m.handleStreamDone(StreamDoneMsg{Channel: ch})
	m = updated.(Model)
	if !m.isStreaming || cmd == nil {
		t.Fatal("delivery end released input before idle")
	}
	updated, cmd = m.Update(sessionReadyMsg{sessionID: sid, channel: ch, err: errors.New("offline")})
	m = updated.(Model)
	if !m.isStreaming || cmd == nil {
		t.Fatal("failed readiness released input")
	}
	updated, _ = m.Update(sessionReadyMsg{sessionID: sid, channel: ch})
	if updated.(Model).isStreaming {
		t.Fatal("confirmed idle did not release input")
	}
}

func TestOldCompletionCannotReleaseNewRequest(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	old := make(chan models.StreamEvent)
	newer := make(chan models.StreamEvent)
	m.streamCh = newer
	m.isStreaming = true
	updated, _ := m.Update(sessionReadyMsg{sessionID: "old", channel: old})
	m = updated.(Model)
	updated, _ = m.handleStreamDone(StreamDoneMsg{Channel: old})
	m = updated.(Model)
	updated, _ = m.handleStreamEvent(StreamEventMsg{Channel: old, Event: models.ErrorEvent{Error: "old"}})
	m = updated.(Model)
	if !m.isStreaming || m.streamCh != newer {
		t.Fatal("old completion changed new request")
	}
}

func TestFailedDraftSurvivesForRetry(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	ch := make(chan models.StreamEvent)
	m.streamCh = ch
	m.isStreaming = true
	m.submittedMessage = "retry me"
	updated, _ := m.handleStreamEvent(StreamEventMsg{Channel: ch, Event: models.ErrorEvent{Error: "offline"}})
	if updated.(Model).input.textInput.Value() != "retry me" {
		t.Fatal("lost failed draft")
	}
}

func TestBusyEnterKeepsDraft(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	m.isStreaming = true
	m.input.textInput.SetValue("next question")
	updated, cmd := m.handleKey(tea.KeyPressMsg{Code: tea.KeyEnter})
	if cmd != nil || updated.(Model).input.textInput.Value() != "next question" {
		t.Fatal("busy submit discarded draft")
	}
}

func TestBusyEnterSelectsPickerItem(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	m.isStreaming = true
	m.readinessUnconfirmed = true
	m.llmModels = []modelOption{{name: "selected-model", label: "Selected model"}}
	m.viewport.showPicker(pickerModel, []pickerItem{{id: "0", label: "Selected model"}})
	updated, _ := m.handleKey(tea.KeyPressMsg{Code: tea.KeyEnter})
	m = updated.(Model)
	if m.viewport.pickerActive || m.modelOverride == nil || *m.modelOverride.ModelVersion != "selected-model" {
		t.Fatal("readiness blocked model selection")
	}
	if !m.isStreaming {
		t.Fatal("picker selection released an unconfirmed turn")
	}
}

type stoppingClient struct {
	api.ClientAPI
	stopped chan int
}

func (c stoppingClient) StopChatSession(_ context.Context, _ string, streamID int) {
	c.stopped <- streamID
}

func TestStopDuringSettlementUsesAcknowledgedIdentity(t *testing.T) {
	client := stoppingClient{stopped: make(chan int, 1)}
	m := NewModel(config.DefaultConfig(), client)
	ch := make(chan models.StreamEvent)
	sid := "session"
	m.chatSessionID = &sid
	m.streamCh = ch
	m.isStreaming = true
	updated, _ := m.handleStreamEvent(StreamEventMsg{Channel: ch, Event: models.MessageIDEvent{ReservedAgentMessageID: 11}})
	m = updated.(Model)
	updated, _ = m.handleStreamDone(StreamDoneMsg{Channel: ch})
	m = updated.(Model)
	m, _ = m.cancelStream()
	if !m.isStreaming {
		t.Fatal("Stop released unsettled request")
	}
	select {
	case id := <-client.stopped:
		if id != 11 {
			t.Fatalf("wrong Stop id %d", id)
		}
	case <-time.After(time.Second):
		t.Fatal("Stop was lost after delivery ended")
	}
}

func TestUnsupportedReadinessStopsPollingWithoutReleasingInput(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	ch := make(chan models.StreamEvent)
	m.streamCh = ch
	m.isStreaming = true
	updated, cmd := m.Update(sessionReadyMsg{sessionID: "session", channel: ch, err: &api.OnyxAPIError{StatusCode: 404, Detail: "Not found"}})
	m = updated.(Model)
	if cmd != nil || !m.isStreaming || !m.readinessUnconfirmed {
		t.Fatal("unsupported endpoint must stop polling without declaring idle")
	}
}

func TestReopeningActiveSessionPreservesReadinessOwner(t *testing.T) {
	for _, settling := range []bool{false, true} {
		m := NewModel(config.DefaultConfig(), nil)
		ch := make(chan models.StreamEvent)
		sid := "session"
		parent := 11
		m.chatSessionID = &sid
		m.parentMessageID = &parent
		m.streamCh = ch
		m.isStreaming = true
		m.settling = settling
		m.viewport.addUserMessage("current question")
		updated, cmd := m.handleSessionResumed(SessionResumedMsg{Detail: &models.ChatSessionDetailResponse{
			ChatSessionID: sid,
			Messages:      []models.ChatMessageDetail{{MessageID: 1, MessageType: "assistant", Message: "earlier answer"}},
		}})
		m = updated.(Model)
		if cmd != nil || !m.isStreaming || m.streamCh != ch || m.parentMessageID != &parent {
			t.Fatal("reopening replaced the active stream or its parent")
		}
		if len(m.viewport.entries) != 1 || m.viewport.entries[0].content != "current question" {
			t.Fatal("reopening replaced live history with the earlier saved snapshot")
		}
		updated, _ = m.Update(sessionReadyMsg{sessionID: sid, channel: ch})
		if updated.(Model).isStreaming {
			t.Fatal("reopening detached the existing readiness callback")
		}
	}
}

func TestRepeatedCtrlDExitsWhileReadinessIsUnconfirmed(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	m.isStreaming = true
	m.readinessUnconfirmed = true
	cancelled := false
	m.streamCancel = func() { cancelled = true }
	key := tea.KeyPressMsg{Code: 'd', Mod: tea.ModCtrl}
	updated, cmd := m.handleKey(key)
	m = updated.(Model)
	if !cancelled || !m.isStreaming || !m.quitPending || cmd == nil {
		t.Fatal("first Ctrl+D must request Stop and arm quit without releasing input")
	}
	updated, cmd = m.handleKey(key)
	m = updated.(Model)
	if cmd == nil {
		t.Fatal("second Ctrl+D must quit")
	}
	if _, ok := cmd().(tea.QuitMsg); !ok {
		t.Fatal("second Ctrl+D did not quit")
	}
	if !m.isStreaming {
		t.Fatal("quit must not mark the server idle")
	}
}

type resumeRequest struct {
	streamID *int
	cursor   int
}

// followingClient serves resume streams in order and a fixed session status.
type followingClient struct {
	decidingClient
	sent     chan models.StreamEvent
	status   models.ChatSessionStatus
	saved    *models.ChatSessionDetailResponse
	streams  []chan models.StreamEvent
	requests []resumeRequest
}

func (c *followingClient) ResumeChatStream(_ context.Context, _ string, streamID *int, cursor int) <-chan models.StreamEvent {
	c.requests = append(c.requests, resumeRequest{streamID, cursor})
	if len(c.streams) == 0 {
		// No stream to follow: the API client reports a 404.
		unavailable := make(chan models.StreamEvent, 1)
		unavailable <- models.StreamUnavailableEvent{}
		close(unavailable)
		return unavailable
	}
	stream := c.streams[0]
	c.streams = c.streams[1:]
	return stream
}

func (c *followingClient) SendMessageStream(context.Context, string, *string, int, *int, []models.FileDescriptorPayload, *models.LLMOverride) <-chan models.StreamEvent {
	return c.sent
}

func (c *followingClient) StopChatSession(context.Context, string, int) {}

func (c *followingClient) ChatSessionStatus(context.Context, string) (models.ChatSessionStatus, error) {
	return c.status, nil
}

func (c *followingClient) GetChatSession(context.Context, string) (*models.ChatSessionDetailResponse, error) {
	return c.saved, nil
}

const followedSession = "11111111-2222-3333-4444-555555555555"

// drain delivers the events of a closed stream.
func drain(t *testing.T, m Model) Model {
	t.Helper()
	for event := range m.streamCh {
		updated, _ := m.handleStreamEvent(StreamEventMsg{Channel: m.streamCh, Event: event})
		m = updated.(Model)
	}
	return m
}

// endStream delivers the end of the current stream and the session status
// that the readiness check reads next.
func endStream(t *testing.T, m Model, status models.ChatSessionStatus) (Model, tea.Cmd) {
	t.Helper()
	ch := m.streamCh
	updated, _ := m.Update(StreamDoneMsg{Channel: ch})
	updated, cmd := updated.(Model).Update(sessionReadyMsg{sessionID: followedSession, channel: ch, status: status})
	return updated.(Model), cmd
}

func TestResumeDuringPreparationFollowsTheStreamOnceItStarts(t *testing.T) {
	streamID := 7
	started := make(chan models.StreamEvent)
	client := &followingClient{saved: &models.ChatSessionDetailResponse{ChatSessionID: followedSession}}
	m := NewModel(config.DefaultConfig(), client)
	// The turn prepares: it runs, but its stream does not exist yet.
	updated, _ := m.Update(SessionResumedMsg{Detail: client.saved, Status: models.ChatSessionStatus{IsProcessing: true}})
	m = updated.(Model)
	m, cmd := endStream(t, m, models.ChatSessionStatus{IsProcessing: true})
	if cmd == nil || !m.isStreaming || len(client.requests) != 1 {
		t.Fatalf("a preparing turn must keep the readiness check: requests=%v", client.requests)
	}

	// The stream starts: the chat loads the session and follows it.
	client.status = models.ChatSessionStatus{IsProcessing: true, StreamID: &streamID}
	client.streams = []chan models.StreamEvent{started}
	m, cmd = endStream(t, m, client.status)
	if cmd == nil {
		t.Fatal("the started stream is not followed")
	}
	resumed, ok := cmd().(SessionResumedMsg)
	if !ok {
		t.Fatal("the started stream is not followed")
	}
	updated, _ = m.Update(resumed)
	m = updated.(Model)
	if len(client.requests) != 2 || client.requests[1].streamID == nil || *client.requests[1].streamID != streamID || client.requests[1].cursor != 0 {
		t.Fatalf("requests = %+v, want stream 7 from cursor 0", client.requests)
	}
	m = receive(t, m, started, approvalRequest("a1"))
	if !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") {
		t.Fatal("the request of the started stream cannot be decided")
	}
}

func TestDroppedFollowContinuesFromItsCursor(t *testing.T) {
	streamID := 7
	first, second := make(chan models.StreamEvent), make(chan models.StreamEvent)
	client := &followingClient{streams: []chan models.StreamEvent{first, second}}
	m := NewModel(config.DefaultConfig(), client)
	updated, _ := m.Update(SessionResumedMsg{
		Detail: &models.ChatSessionDetailResponse{ChatSessionID: followedSession},
		Status: models.ChatSessionStatus{IsProcessing: true, StreamID: &streamID},
	})
	m = updated.(Model)
	m = receive(t, m, first, models.MessageDeltaEvent{Content: "Filing the ticket."})
	m = receive(t, m, first, models.StreamCursorEvent{StreamID: streamID, NextCursor: 4})

	// The connection drops while the response still runs.
	m, _ = endStream(t, m, models.ChatSessionStatus{IsProcessing: true, StreamID: &streamID})
	if len(client.requests) != 2 || client.requests[1].streamID == nil || *client.requests[1].streamID != streamID || client.requests[1].cursor != 4 {
		t.Fatalf("requests = %+v, want stream 7 from cursor 4", client.requests)
	}
	if m.streamCh != second || !m.isStreaming {
		t.Fatal("the response is not followed again")
	}
	m = receive(t, m, second, approvalRequest("a1"))
	if !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") {
		t.Fatal("a request raised after the drop cannot be decided")
	}
	if view := stripANSI(m.viewport.view(20)); strings.Count(view, "Filing the ticket.") != 1 {
		t.Fatalf("the response does not show once:\n%s", view)
	}
}

func TestStreamWithoutBufferIsNotRequestedAgain(t *testing.T) {
	streamID := 7
	client := &followingClient{}
	m := NewModel(config.DefaultConfig(), client)
	running := models.ChatSessionStatus{IsProcessing: true, StreamID: &streamID}
	updated, _ := m.Update(SessionResumedMsg{Detail: &models.ChatSessionDetailResponse{ChatSessionID: followedSession}, Status: running})
	m = drain(t, updated.(Model))
	m, cmd := endStream(t, m, running)
	if cmd == nil || !m.isStreaming || len(client.requests) != 1 {
		t.Fatalf("a stream without a buffer was requested again: %+v", client.requests)
	}
	if _, polled := cmd().(sessionReadyMsg); !polled {
		t.Fatal("the readiness check stopped")
	}
}

func TestStoppedFollowIsNotFollowedAgain(t *testing.T) {
	streamID := 7
	stream := make(chan models.StreamEvent)
	client := &followingClient{streams: []chan models.StreamEvent{stream}}
	m := NewModel(config.DefaultConfig(), client)
	running := models.ChatSessionStatus{IsProcessing: true, StreamID: &streamID}
	updated, _ := m.Update(SessionResumedMsg{Detail: &models.ChatSessionDetailResponse{ChatSessionID: followedSession}, Status: running})
	m = updated.(Model)
	m = receive(t, m, stream, models.StreamCursorEvent{StreamID: streamID, NextCursor: 1})
	m, _ = m.cancelStream()
	m, _ = endStream(t, m, running)
	if len(client.requests) != 1 || !m.isStreaming {
		t.Fatalf("a stopped response was followed again: %+v", client.requests)
	}
}

func TestRejectedMessageDoesNotFollowAnotherResponse(t *testing.T) {
	streamID := 7
	client := &followingClient{}
	m, ch := streamingModel(client)
	session := followedSession
	m.chatSessionID = &session
	m = receive(t, m, ch, models.ErrorEvent{Error: "HTTP 400: bad request", StatusCode: 400})
	m, cmd := endStream(t, m, models.ChatSessionStatus{IsProcessing: true, StreamID: &streamID})
	if cmd == nil || !m.isStreaming || len(client.requests) != 0 {
		t.Fatalf("a rejected message followed another response: %+v", client.requests)
	}
	if _, polled := cmd().(sessionReadyMsg); !polled {
		t.Fatal("the readiness check stopped")
	}
}

func TestStopAfterReattachReachesTheServer(t *testing.T) {
	stopped := make(chan string, 2)
	mux := http.NewServeMux()
	mux.HandleFunc("/api/chat/chat-session/"+followedSession+"/resume-stream", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("cursor") != "4" || r.URL.Query().Get("stream_id") != "7" {
			http.Error(w, "unexpected cursor", http.StatusBadRequest)
			return
		}
		fmt.Fprintln(w, `{"placement":{"turn_index":0},"obj":{"type":"message_delta","content":"more"}}`)
		fmt.Fprintln(w, `{"stream_id":7,"next_cursor":5,"replay_complete":true}`)
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	})
	mux.HandleFunc("/api/chat/stop-chat-session/"+followedSession, func(w http.ResponseWriter, r *http.Request) {
		stopped <- r.URL.Query().Get("stream_id")
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	streamID, cursor := 7, 4
	m := NewModel(config.DefaultConfig(), testutil.NewClient(server.URL))
	session := followedSession
	ended := make(chan models.StreamEvent)
	close(ended)
	m.chatSessionID = &session
	m.isStreaming = true
	m.following = true
	m.streamID = &streamID
	m.resumeCursor = &cursor
	m.streamCh = ended
	m, _ = endStream(t, m, models.ChatSessionStatus{IsProcessing: true, StreamID: &streamID})
	for {
		event, ok := <-m.streamCh
		if !ok {
			t.Fatal("the reattached stream ended")
		}
		if e, failed := event.(models.ErrorEvent); failed {
			t.Fatalf("the reattached stream failed: %s", e.Error)
		}
		updated, _ := m.handleStreamEvent(StreamEventMsg{Channel: m.streamCh, Event: event})
		m = updated.(Model)
		if _, isCursor := event.(models.StreamCursorEvent); isCursor {
			break
		}
	}
	if *m.resumeCursor != 5 {
		t.Fatalf("cursor = %d, want 5", *m.resumeCursor)
	}

	m, _ = m.cancelStream()
	select {
	case id := <-stopped:
		if id != "7" {
			t.Fatalf("Stop stream_id = %q, want 7", id)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Stop did not reach the server")
	}
	for range m.streamCh {
	}
	if len(stopped) != 0 {
		t.Fatal("Stop was sent twice")
	}
}

func TestDroppedResponseKeepsInputBlockedUntilTheSessionLoads(t *testing.T) {
	streamID := 7
	running := make(chan models.StreamEvent)
	client := &followingClient{streams: []chan models.StreamEvent{running}}
	client.status = models.ChatSessionStatus{IsProcessing: true, StreamID: &streamID}
	client.saved = &models.ChatSessionDetailResponse{ChatSessionID: followedSession}
	client.sent = make(chan models.StreamEvent)
	m, ch := streamingModel(client)
	session := followedSession
	m.chatSessionID = &session
	m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: streamID})
	// The send stream drops while its response runs.
	m, cmd := endStream(t, m, client.status)
	if cmd == nil || !m.isStreaming {
		t.Fatal("input was released before the session loaded again")
	}
	m, sendCmd := m.sendMessage("next question")
	if sendCmd != nil {
		t.Fatal("a message was sent while the session loads again")
	}
	updated, _ := m.Update(cmd())
	m = updated.(Model)
	if m.streamCh != running || !m.isStreaming || len(client.requests) != 1 || *client.requests[0].streamID != streamID {
		t.Fatalf("the running response is not followed: %+v", client.requests)
	}
}

func TestCleanCloseBeforeTheFirstCursorIsRetried(t *testing.T) {
	streamID := 7
	closed, again := make(chan models.StreamEvent), make(chan models.StreamEvent)
	close(closed)
	client := &followingClient{streams: []chan models.StreamEvent{closed, again}}
	client.status = models.ChatSessionStatus{IsProcessing: true, StreamID: &streamID}
	client.saved = &models.ChatSessionDetailResponse{ChatSessionID: followedSession}
	m := NewModel(config.DefaultConfig(), client)
	updated, _ := m.Update(SessionResumedMsg{Detail: client.saved, Status: client.status})
	m = drain(t, updated.(Model))
	m, cmd := endStream(t, m, client.status)
	if cmd == nil {
		t.Fatal("the response is not followed again")
	}
	resumed, ok := cmd().(SessionResumedMsg)
	if !ok {
		t.Fatal("the response is not followed again")
	}
	updated, _ = m.Update(resumed)
	m = updated.(Model)
	if m.streamCh != again || len(client.requests) != 2 {
		t.Fatalf("requests = %+v, want a second request for stream 7", client.requests)
	}
}

func TestReloadAfterTheUserLeavesIsIgnored(t *testing.T) {
	for name, leave := range map[string]func(Model) Model{
		"clear": func(m Model) Model {
			m, _ = cmdNew(m)
			return m
		},
		"another session": func(m Model) Model {
			updated, _ := m.Update(SessionResumedMsg{
				Detail: &models.ChatSessionDetailResponse{ChatSessionID: "other-session"},
				Status: models.ChatSessionStatus{IsProcessing: true},
			})
			return updated.(Model)
		},
	} {
		t.Run(name, func(t *testing.T) {
			streamID := 7
			other := make(chan models.StreamEvent)
			client := &followingClient{streams: []chan models.StreamEvent{other}}
			client.status = models.ChatSessionStatus{IsProcessing: true, StreamID: &streamID}
			client.saved = &models.ChatSessionDetailResponse{ChatSessionID: followedSession}
			client.sent = make(chan models.StreamEvent)
			m, ch := streamingModel(client)
			session := followedSession
			m.chatSessionID = &session
			m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: streamID})
			m, reload := endStream(t, m, client.status)
			m = leave(m)
			current, isStreaming := m.chatSessionID, m.isStreaming

			updated, _ := m.Update(reload())
			m = updated.(Model)
			if m.chatSessionID != current || m.isStreaming != isStreaming || len(client.requests) > 1 {
				t.Fatalf("the stale reload took over: session=%v requests=%+v", m.chatSessionID, client.requests)
			}
		})
	}
}

func TestFollowedResponseKeepsTheSessionName(t *testing.T) {
	stream := make(chan models.StreamEvent)
	client := &followingClient{streams: []chan models.StreamEvent{stream}}
	m := NewModel(config.DefaultConfig(), client)
	updated, _ := m.Update(SessionResumedMsg{
		Detail: &models.ChatSessionDetailResponse{ChatSessionID: followedSession},
		Status: models.ChatSessionStatus{IsProcessing: true},
	})
	m = updated.(Model)
	m = receive(t, m, stream, models.SessionCreatedEvent{ChatSessionID: followedSession})
	if m.needsRename {
		t.Fatal("the replayed session creation asks to rename the session")
	}
}
