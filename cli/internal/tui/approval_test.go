package tui

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

type decidingClient struct {
	api.ClientAPI
	decisions []models.ApprovalDecision
	// The decision the server saves; by default, the one sent.
	result *models.ApprovalDecisionResult
	err    error
}

func (c *decidingClient) DecideApproval(_ context.Context, approvalID string, decision models.ApprovalDecision) (models.ApprovalDecisionResult, error) {
	c.decisions = append(c.decisions, decision)
	if c.result != nil {
		return *c.result, c.err
	}
	result := models.ApprovalDecisionResult{ApprovalID: approvalID, Decision: "APPROVED", DecidedVia: "USER"}
	switch decision {
	case models.RejectApproval:
		result.Decision = "REJECTED"
	case models.ApproveSession:
		result.DecidedVia = "SESSION_GRANT"
	}
	return result, c.err
}

func streamingModel(client api.ClientAPI) (Model, chan models.StreamEvent) {
	m := NewModel(config.DefaultConfig(), client)
	ch := make(chan models.StreamEvent)
	m.streamCh = ch
	m.isStreaming = true
	return m, ch
}

func approvalRequest(id string) models.ToolApprovalRequestEvent {
	return models.ToolApprovalRequestEvent{
		ApprovalID:  id,
		ToolName:    "mcp__3__linear__create_issue",
		DisplayName: "Create issue",
		Arguments:   map[string]any{"title": "Bug"},
	}
}

func receive(t *testing.T, m Model, ch chan models.StreamEvent, event models.StreamEvent) Model {
	t.Helper()
	updated, _ := m.handleStreamEvent(StreamEventMsg{Channel: ch, Event: event})
	return updated.(Model)
}

func press(t *testing.T, m Model, key tea.KeyPressMsg) (Model, tea.Cmd) {
	t.Helper()
	updated, cmd := m.handleKey(key)
	return updated.(Model), cmd
}

func approvalEntry(t *testing.T, m Model, id string) string {
	t.Helper()
	for _, e := range m.viewport.entries {
		if e.kind == entryApproval && e.approvalID == id {
			return stripANSI(e.rendered)
		}
	}
	t.Fatalf("no entry for approval %s", id)
	return ""
}

// decide runs the decision command and feeds its result back to the model.
func decide(t *testing.T, m Model, cmd tea.Cmd) Model {
	t.Helper()
	if cmd == nil {
		t.Fatal("no decision was sent")
	}
	updated, _ := m.Update(cmd())
	return updated.(Model)
}

func TestApprovalShortcutsDecide(t *testing.T) {
	tests := []struct {
		key      rune
		decision models.ApprovalDecision
		outcome  string
		record   string
	}{
		{'y', models.ApproveOnce, "approved", "Approved: Create issue"},
		{'a', models.ApproveSession, "approved_for_chat", "Approved for this session: Create issue"},
		{'n', models.RejectApproval, "rejected", "Not approved: Create issue"},
	}
	for _, tt := range tests {
		t.Run(string(tt.key), func(t *testing.T) {
			client := &decidingClient{}
			m, ch := streamingModel(client)
			m = receive(t, m, ch, approvalRequest("a1"))
			card := approvalEntry(t, m, "a1")
			for _, want := range []string{"Approval requested: Create issue", "title: Bug", "> Approve once (y)", "Reject (n)"} {
				if !strings.Contains(card, want) {
					t.Fatalf("card lacks %q:\n%s", want, card)
				}
			}

			m, cmd := press(t, m, tea.KeyPressMsg{Code: tt.key, Text: string(tt.key)})
			if !strings.Contains(approvalEntry(t, m, "a1"), "Sending") {
				t.Fatal("card does not show the decision in flight")
			}
			m = decide(t, m, cmd)
			if len(client.decisions) != 1 || client.decisions[0] != tt.decision {
				t.Fatalf("decisions = %v, want [%s]", client.decisions, tt.decision)
			}
			if got := approvalEntry(t, m, "a1"); got != "● "+tt.record {
				t.Fatalf("record = %q, want %q", got, "● "+tt.record)
			}
			if !m.isStreaming || m.activeApproval() >= 0 {
				t.Fatal("decision must close the card for input and keep the stream")
			}
			// The server's resolved packet repeats the outcome and ends the card.
			m = receive(t, m, ch, models.ToolApprovalResolvedEvent{ApprovalID: "a1", Outcome: tt.outcome})
			if got := approvalEntry(t, m, "a1"); got != "● "+tt.record || len(m.approvals) != 0 {
				t.Fatalf("resolved packet changed the record: %q", got)
			}
		})
	}
}

func TestServerOutcomeOutranksTheLocalDecision(t *testing.T) {
	m, ch := streamingModel(&decidingClient{})
	m = receive(t, m, ch, approvalRequest("a1"))
	m = receive(t, m, ch, approvalRequest("a2"))
	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	m = decide(t, m, cmd)
	if !strings.Contains(approvalEntry(t, m, "a2"), "> Approve once (y)") {
		t.Fatal("the next card did not become active after the decision")
	}

	// A Stop cancelled the call before the approval applied.
	m = receive(t, m, ch, models.ToolApprovalResolvedEvent{ApprovalID: "a1", Outcome: "cancelled"})
	if got := approvalEntry(t, m, "a1"); got != "● No longer waiting: Create issue" {
		t.Fatalf("record = %q, want the server outcome", got)
	}

	// Without the server's outcome, the card keeps this client's decision.
	m, cmd = press(t, m, tea.KeyPressMsg{Code: 'n', Text: "n"})
	m = decide(t, m, cmd)
	m, _ = m.finishStream(nil)
	if got := approvalEntry(t, m, "a2"); got != "● Not approved: Create issue" || len(m.approvals) != 0 {
		t.Fatalf("record = %q", got)
	}
}

func TestApprovingADisabledToolRecordsItDisabled(t *testing.T) {
	client := &decidingClient{result: &models.ApprovalDecisionResult{ApprovalID: "a1", Decision: "REJECTED", DecidedVia: "POLICY"}}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, approvalRequest("a1"))

	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	m = decide(t, m, cmd)

	if got, want := approvalEntry(t, m, "a1"), "● Disabled: Create issue"; got != want {
		t.Fatalf("record = %q, want %q", got, want)
	}
}

func TestApprovalPickerSelectsWithArrowsAndEnter(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, approvalRequest("a1"))
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyDown})
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyDown})
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyDown})
	if !strings.Contains(approvalEntry(t, m, "a1"), "> Reject (n)") {
		t.Fatal("down arrow did not move the selection to Reject")
	}
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	decide(t, m, cmd)
	if len(client.decisions) != 1 || client.decisions[0] != models.RejectApproval {
		t.Fatalf("decisions = %v", client.decisions)
	}
}

func TestApprovalKeepsDraftAndBlocksSend(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, approvalRequest("a1"))
	m.input.textInput.Focus()
	m.input.textInput.SetValue("next question")

	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if cmd != nil || m.input.textInput.Value() != "next question" {
		t.Fatal("Enter with a draft must not send or decide")
	}
	if last := m.viewport.entries[len(m.viewport.entries)-1]; !strings.Contains(last.content, "Approve or reject the tool call first") {
		t.Fatalf("no blocked-send message, last entry %q", last.content)
	}
	m, _ = press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	if len(client.decisions) != 0 || m.input.textInput.Value() != "next questiony" {
		t.Fatalf("a shortcut typed into a draft must stay text: decisions=%v draft=%q", client.decisions, m.input.textInput.Value())
	}
	if len(m.approvals) != 1 {
		t.Fatal("card left without a decision")
	}
}

func TestApprovalResolvedOutcomes(t *testing.T) {
	for outcome, record := range map[string]string{
		"approved":          "Approved",
		"approved_for_chat": "Approved for this session",
		"rejected":          "Not approved",
		"disabled":          "Disabled",
		"cancelled":         "No longer waiting",
		"deferred":          "No longer waiting",
	} {
		t.Run(outcome, func(t *testing.T) {
			m, ch := streamingModel(&decidingClient{})
			m = receive(t, m, ch, approvalRequest("a1"))
			m = receive(t, m, ch, models.ToolApprovalResolvedEvent{ApprovalID: "a1", Outcome: outcome})
			if got := approvalEntry(t, m, "a1"); got != "● "+record+": Create issue" {
				t.Fatalf("record = %q", got)
			}
		})
	}
}

func TestApprovalDecisionErrors(t *testing.T) {
	t.Run("no longer waiting", func(t *testing.T) {
		client := &decidingClient{err: &api.OnyxAPIError{StatusCode: 409, Detail: "already decided"}}
		m, ch := streamingModel(client)
		m = receive(t, m, ch, approvalRequest("a1"))
		m, cmd := press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
		m = decide(t, m, cmd)
		if got := approvalEntry(t, m, "a1"); got != "● No longer waiting: Create issue" {
			t.Fatalf("record = %q", got)
		}
	})
	t.Run("retryable failure", func(t *testing.T) {
		client := &decidingClient{err: errors.New("connection refused")}
		m, ch := streamingModel(client)
		m = receive(t, m, ch, approvalRequest("a1"))
		m, cmd := press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
		m = decide(t, m, cmd)
		if len(m.approvals) != 1 || m.approvals[0].sending != "" {
			t.Fatal("a failed decision must leave the card open for another try")
		}
		if !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") {
			t.Fatal("card does not offer the actions again")
		}
		if last := m.viewport.entries[len(m.viewport.entries)-1]; !strings.Contains(last.content, "connection refused") {
			t.Fatalf("error not shown, last entry %q", last.content)
		}
	})
}

func TestApprovalQueueActivatesInOrder(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, approvalRequest("a1"))
	m = receive(t, m, ch, approvalRequest("a2"))
	if !strings.Contains(approvalEntry(t, m, "a2"), "Waits for the request above") {
		t.Fatal("second card must wait for the first")
	}
	m = receive(t, m, ch, models.ToolApprovalResolvedEvent{ApprovalID: "a1", Outcome: "rejected"})
	if !strings.Contains(approvalEntry(t, m, "a2"), "> Approve once (y)") {
		t.Fatal("second card did not become active")
	}
}

func TestEscWhileApprovalWaitsUsesStop(t *testing.T) {
	m, ch := streamingModel(&decidingClient{})
	m = receive(t, m, ch, approvalRequest("a1"))
	for _, key := range []tea.KeyPressMsg{{Code: tea.KeyEscape}, {Code: 'c', Mod: tea.ModCtrl}} {
		cancelled := false
		m.streamCancel = func() { cancelled = true }
		m, _ = press(t, m, key)
		if !cancelled || !m.isStreaming {
			t.Fatalf("%s must request Stop and keep the turn until it settles", key.String())
		}
	}
	// The Stop rejects the request; the cut stream reports no outcome.
	m, _ = m.finishStream(nil)
	if got := approvalEntry(t, m, "a1"); got != "● Not approved: Create issue" || len(m.approvals) != 0 {
		t.Fatalf("stopped stream left %q, want the rejection", got)
	}
}

func TestApprovalCardStripsHostileContent(t *testing.T) {
	m, ch := streamingModel(&decidingClient{})
	request := approvalRequest("a1")
	request.DisplayName = "Create\x1b]52;c;ZWNobyBoaQ==\x07 issue"
	request.Arguments = map[string]any{"cmd\x1b[2J": "rm -rf ~\x1b]8;;https://evil\x1b\\\nnext\rline"}
	m = receive(t, m, ch, request)
	var rendered string
	for _, e := range m.viewport.entries {
		if e.kind == entryApproval {
			rendered = e.rendered
		}
	}
	for _, injected := range []string{"\x1b]52;", "\x1b]8;", "\x1b[2J", "\x07", "\r"} {
		if strings.Contains(rendered, injected) {
			t.Fatalf("card keeps the injected sequence %q: %q", injected, rendered)
		}
	}
	plain := stripANSI(rendered)
	if strings.ContainsAny(plain, "\x1b\x07\r") {
		t.Fatalf("card keeps control characters: %q", plain)
	}
	if !strings.Contains(plain, "Approval requested: Create issue") || !strings.Contains(plain, "cmd: rm -rf ~ nextline") {
		t.Fatalf("card = %q", plain)
	}
}

// resumingClient serves a session's running response.
type resumingClient struct {
	decidingClient
	running chan models.StreamEvent
	resumed []string
	// sent answers SendMessageStream.
	sent chan models.StreamEvent
	// saved answers GetChatSession.
	saved *models.ChatSessionDetailResponse
	// status answers ChatSessionStatus when set.
	status *models.ChatSessionStatus
	// statusErr fails ChatSessionStatus.
	statusErr error
	// stops receives the stream ID of each Stop.
	stops chan int
}

func (c *resumingClient) SendMessageStream(context.Context, string, *string, int, *int, []models.FileDescriptorPayload, *models.LLMOverride) <-chan models.StreamEvent {
	return c.sent
}

func (c *resumingClient) ResumeChatStream(_ context.Context, sessionID string, _ *int, _ int) <-chan models.StreamEvent {
	c.resumed = append(c.resumed, sessionID)
	return c.running
}

func (c *resumingClient) StopChatSession(_ context.Context, _ string, streamID int) {
	c.stops <- streamID
}

const waitingSessionID = "11111111-2222-3333-4444-555555555555"

// waitingSession is a saved session whose response 2 waits for a1.
func waitingSession(t *testing.T) *models.ChatSessionDetailResponse {
	t.Helper()
	packet := func(obj map[string]any) json.RawMessage {
		line, err := json.Marshal(map[string]any{"placement": map[string]any{"turn_index": 0}, "obj": obj})
		if err != nil {
			t.Fatal(err)
		}
		return line
	}
	return &models.ChatSessionDetailResponse{
		ChatSessionID: waitingSessionID,
		Messages: []models.ChatMessageDetail{
			{MessageID: 1, MessageType: "user", Message: "file a ticket"},
			{MessageID: 2, MessageType: "assistant", Message: "Filing the ticket."},
		},
		Packets: [][]json.RawMessage{{
			packet(map[string]any{"type": "message_delta", "content": "Filing the ticket."}),
			packet(map[string]any{"type": "tool_approval_request", "approval_id": "a1", "tool_name": "mcp__3__linear__create_issue", "display_name": "Create issue", "arguments": map[string]any{"title": "Bug"}}),
			packet(map[string]any{"type": "stop", "stop_reason": "awaiting_approval"}),
		}},
	}
}

// run runs cmd and feeds its message back to the model.
func run(t *testing.T, m Model, cmd tea.Cmd) (Model, tea.Cmd) {
	t.Helper()
	if cmd == nil {
		t.Fatal("no command")
	}
	updated, next := m.Update(cmd())
	return updated.(Model), next
}

func TestApprovalPendingErrorShowsTheWaitingRequestAndKeepsDraft(t *testing.T) {
	client := &resumingClient{sent: make(chan models.StreamEvent), saved: waitingSession(t)}
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m.viewport.startAgent()
	m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: 2})
	m = receive(t, m, ch, models.MessageDeltaEvent{Content: "Filing the ticket."})
	m, _ = m.finishStream(nil)

	m, _ = m.sendMessage("follow-up")
	updated, cmd := m.handleStreamEvent(StreamEventMsg{Channel: client.sent, Event: models.ErrorEvent{Error: "HTTP 409: Approve or reject", StatusCode: 409, ErrorCode: api.ErrorCodeApprovalPending}})
	m = updated.(Model)
	var warning string
	for _, e := range m.viewport.entries {
		if e.kind == entryError {
			warning = e.content
		}
	}
	if !strings.Contains(warning, "waits for approval") || strings.Contains(warning, "409") {
		t.Fatalf("message = %q", warning)
	}

	// The waiting response has no stream; the saved session shows its request.
	m, _ = run(t, m, cmd)
	if len(client.resumed) != 0 {
		t.Fatalf("followed a stream: resumed=%v", client.resumed)
	}
	if m.input.textInput.Value() != "follow-up" {
		t.Fatal("lost the draft")
	}
	shown, cards := 0, 0
	for _, e := range m.viewport.entries {
		if e.kind == entryUser && e.content == "follow-up" {
			t.Fatalf("the unsent message shows: %q", e.content)
		}
		shown += strings.Count(e.content, "Filing the ticket.")
		if e.kind == entryApproval {
			cards++
		}
	}
	if shown != 1 || cards != 1 {
		t.Fatalf("the response shows %d times and its request %d times", shown, cards)
	}
	if !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") || !m.isStreaming {
		t.Fatal("the waiting request cannot be decided")
	}
}

func TestStopForDecisionsKeepsCardsAndTheLastDecisionFollowsTheContinuation(t *testing.T) {
	client := &resumingClient{running: make(chan models.StreamEvent)}
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m.viewport.startAgent()
	m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: 2})
	m = receive(t, m, ch, approvalRequest("a1"))
	m = receive(t, m, ch, approvalRequest("a2"))
	reason := models.StopReasonAwaitingApproval
	m = receive(t, m, ch, models.StopEvent{StopReason: &reason})
	updated, cmd := m.Update(StreamDoneMsg{Channel: ch})
	m = updated.(Model)
	if cmd != nil {
		t.Fatal("the client keeps reading after the stream stopped for decisions")
	}
	if !m.isStreaming || m.activeApproval() != 0 {
		t.Fatal("the cards are not actionable")
	}

	// The first decision leaves a2 waiting, so nothing follows yet.
	m, cmd = press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	m, next := run(t, m, cmd)
	if next != nil || m.activeApproval() != 1 {
		t.Fatal("followed the response before every request was decided")
	}

	// The last decision checks the status, which names the continuation.
	client.status = &models.ChatSessionStatus{IsProcessing: true, StreamID: new(3)}
	client.saved = &models.ChatSessionDetailResponse{
		ChatSessionID: session,
		Messages: []models.ChatMessageDetail{
			{MessageID: 1, MessageType: "user", Message: "file a ticket"},
			{MessageID: 2, MessageType: "assistant"},
		},
	}
	m, cmd = press(t, m, tea.KeyPressMsg{Code: 'n', Text: "n"})
	m, ready := run(t, m, cmd)
	m, reload := run(t, m, ready)
	m, _ = run(t, m, reload)
	if len(client.resumed) != 1 || m.streamCh != client.running {
		t.Fatalf("did not follow the continuation: resumed=%v", client.resumed)
	}
	m = receive(t, m, client.running, models.ToolApprovalResolvedEvent{ApprovalID: "a1", Outcome: "approved"})
	m = receive(t, m, client.running, models.MessageDeltaEvent{Content: "Filed ENG-1."})
	if view := stripANSI(m.viewport.view(20)); !strings.Contains(view, "Filed ENG-1.") {
		t.Fatalf("the continuation does not show:\n%s", view)
	}
}

func TestResumingAWaitingSessionShowsItsRequestThatStopCannotEnd(t *testing.T) {
	client := &resumingClient{stops: make(chan int, 1)}
	m := NewModel(config.DefaultConfig(), client)
	m, _ = run(t, m, func() tea.Msg { return SessionResumedMsg{Detail: waitingSession(t)} })
	if !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") || !m.isStreaming {
		t.Fatal("the waiting request cannot be decided")
	}
	if len(client.resumed) != 0 {
		t.Fatalf("followed a stream: resumed=%v", client.resumed)
	}

	card := approvalEntry(t, m, "a1")
	if strings.Contains(card, "esc stop the response") {
		t.Fatalf("the card offers Stop for a waiting response:\n%s", card)
	}
	for _, key := range []tea.KeyPressMsg{{Code: tea.KeyEscape}, {Code: 'c', Mod: tea.ModCtrl}} {
		updated, cmd := m.handleKey(key)
		m = updated.(Model)
		if cmd != nil || m.stopRequested {
			t.Fatalf("%s acted on a waiting response", key.String())
		}
	}
	select {
	case got := <-client.stops:
		t.Fatalf("sent Stop for stream %d", got)
	default:
	}
	if !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") || !m.isStreaming {
		t.Fatal("the waiting request cannot be decided after Esc")
	}
}

func TestResumingARunningSessionShowsItsWaitingRequest(t *testing.T) {
	client := &resumingClient{running: make(chan models.StreamEvent)}
	m := NewModel(config.DefaultConfig(), client)
	updated, _ := m.Update(SessionResumedMsg{
		Detail: &models.ChatSessionDetailResponse{
			ChatSessionID: "session-1",
			Messages: []models.ChatMessageDetail{
				{MessageID: 1, MessageType: "user", Message: "file a ticket"},
				{MessageID: 2, MessageType: "assistant", Message: "partial"},
			},
		},
		Status: models.ChatSessionStatus{IsProcessing: true},
	})
	m = updated.(Model)

	if len(client.resumed) != 1 || client.resumed[0] != "session-1" || !m.isStreaming {
		t.Fatalf("did not follow the running response: resumed=%v", client.resumed)
	}
	// The replay of the response replaces its saved copy.
	m = receive(t, m, client.running, models.MessageIDEvent{ReservedAgentMessageID: 2})
	for _, e := range m.viewport.entries {
		if strings.Contains(e.content, "partial") {
			t.Fatal("the running response shows twice")
		}
	}
	m = receive(t, m, client.running, approvalRequest("a1"))
	if !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") {
		t.Fatal("the waiting request cannot be decided")
	}
}

func (c *resumingClient) GetChatSession(_ context.Context, sessionID string) (*models.ChatSessionDetailResponse, error) {
	return c.saved, nil
}

func (c *resumingClient) ChatSessionStatus(context.Context, string) (models.ChatSessionStatus, error) {
	if c.status != nil {
		return *c.status, nil
	}
	// Like the API client, a failed query reports a running session.
	return models.ChatSessionStatus{IsProcessing: c.statusErr != nil}, c.statusErr
}

func TestResumeFollowsTheSessionWhenItsStatusIsUnknown(t *testing.T) {
	const sessionID = "11111111-2222-3333-4444-555555555555"
	client := &resumingClient{
		saved:     &models.ChatSessionDetailResponse{ChatSessionID: sessionID},
		statusErr: errors.New("connection reset"),
	}
	_, cmd := cmdResume(NewModel(config.DefaultConfig(), client), sessionID, nil)
	if msg := cmd().(SessionResumedMsg); !msg.Status.IsProcessing {
		t.Fatal("a failed status query skips the stream that shows a waiting request")
	}
}

func TestResumeKeepsTheSavedResponseWhenReplayIsUnavailable(t *testing.T) {
	// The run ends before the replay starts, so the replay has no events.
	running := make(chan models.StreamEvent)
	close(running)
	client := &resumingClient{running: running}
	const sessionID = "11111111-2222-3333-4444-555555555555"
	m := NewModel(config.DefaultConfig(), client)
	question := models.ChatMessageDetail{MessageID: 1, MessageType: "user", Message: "file a ticket"}
	updated, _ := m.Update(SessionResumedMsg{
		Detail: &models.ChatSessionDetailResponse{
			ChatSessionID: sessionID,
			Messages:      []models.ChatMessageDetail{question, {MessageID: 2, MessageType: "assistant", Message: "Filing"}},
		},
		Status: models.ChatSessionStatus{IsProcessing: true},
	})
	m = updated.(Model)
	updated, _ = m.Update(StreamDoneMsg{Channel: m.streamCh})
	m = updated.(Model)
	updated, cmd := m.Update(sessionReadyMsg{sessionID: sessionID, channel: m.streamCh})
	m = updated.(Model)
	if !strings.Contains(stripANSI(m.viewport.view(20)), "Filing") {
		t.Fatalf("the saved response is gone:\n%s", stripANSI(m.viewport.view(20)))
	}
	if !m.isStreaming {
		t.Fatal("input was released before the session loaded again")
	}

	// The session loads again with the finished response.
	if cmd == nil {
		t.Fatal("the session was not loaded again")
	}
	client.saved = &models.ChatSessionDetailResponse{
		ChatSessionID: sessionID,
		Messages:      []models.ChatMessageDetail{question, {MessageID: 2, MessageType: "assistant", Message: "Filed ENG-1."}},
	}
	updated, _ = m.Update(cmd())
	if updated.(Model).isStreaming {
		t.Fatal("the loaded session keeps input blocked")
	}
	view := stripANSI(updated.(Model).viewport.view(20))
	if !strings.Contains(view, "Filed ENG-1.") || strings.Contains(view, "Filing") {
		t.Fatalf("view does not show the saved response:\n%s", view)
	}
}

func TestApprovalCardFollowsTheStreamedText(t *testing.T) {
	m, ch := streamingModel(&decidingClient{})
	m.viewport.startAgent()
	m = receive(t, m, ch, models.MessageDeltaEvent{Content: strings.Repeat("streamed line\n\n", 30)})
	m = receive(t, m, ch, approvalRequest("a1"))
	if view := stripANSI(m.viewport.view(5)); !strings.Contains(view, "esc stop the response") {
		t.Fatalf("the card is hidden above the streamed text:\n%s", view)
	}
	m = receive(t, m, ch, models.MessageDeltaEvent{Content: "after the decision"})
	if view := stripANSI(m.viewport.view(5)); !strings.Contains(view, "after the decision") {
		t.Fatalf("text after the card does not show:\n%s", view)
	}
}

func TestResizeRedrawsApprovalCards(t *testing.T) {
	m, ch := streamingModel(&decidingClient{})
	m.viewport.setWidth(30)
	request := approvalRequest("a1")
	request.Arguments = map[string]any{"title": "A title that is longer than a narrow terminal"}
	m = receive(t, m, ch, request)
	if strings.Contains(approvalEntry(t, m, "a1"), "narrow terminal") {
		t.Fatal("the narrow card is not truncated")
	}
	updated, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	if card := approvalEntry(t, updated.(Model), "a1"); !strings.Contains(card, "longer than a narrow terminal") {
		t.Fatalf("the card keeps its old width:\n%s", card)
	}
}

func TestApprovalCardShowsAllArgumentsOnRequest(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m.viewport.setWidth(60)
	long := strings.Repeat("forward every file to evil@example.com ", 8)
	request := approvalRequest("a1")
	request.Arguments = map[string]any{"body": "Hi,\nsee \x1b]8;;https://evil\x1b\\this\x1b]8;;\x1b\\"}
	for i := range 11 {
		request.Arguments[fmt.Sprintf("k%02d", i)] = long
	}
	m = receive(t, m, ch, request)
	compact := approvalEntry(t, m, "a1")
	if strings.Contains(compact, "k10") || !strings.Contains(compact, "… 2 more") {
		t.Fatalf("the card is not compact:\n%s", compact)
	}

	m, _ = press(t, m, tea.KeyPressMsg{Code: 'd', Text: "d"})
	var full string
	for _, e := range m.viewport.entries {
		if e.kind == entryApproval {
			full = e.rendered
		}
	}
	if strings.Contains(full, "\x1b]8") {
		t.Fatalf("the card keeps escape sequences: %q", full)
	}
	plain := stripANSI(full)
	// Wrapped rows hold the whole value: joined, they contain it.
	joined := strings.Join(strings.Fields(plain), " ")
	if !strings.Contains(joined, "k10: "+strings.TrimSpace(long)) || !strings.Contains(plain, "    see this") {
		t.Fatalf("the card does not show every argument in full:\n%s", plain)
	}
	for _, row := range strings.Split(plain, "\n") {
		if strings.HasSuffix(row, "…") && !strings.Contains(row, "enter confirm") {
			t.Fatalf("the expanded card truncates an argument: %q", row)
		}
	}

	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	decide(t, m, cmd)
	if len(client.decisions) != 1 || client.decisions[0] != models.ApproveOnce {
		t.Fatalf("decisions = %v", client.decisions)
	}
}
