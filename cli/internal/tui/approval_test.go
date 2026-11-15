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
	// The continuation that the default result names.
	continuation *models.ChatStream
	err          error
}

func (c *decidingClient) DecideApproval(_ context.Context, approvalID string, decision models.ApprovalDecision) (models.ApprovalDecisionResult, error) {
	c.decisions = append(c.decisions, decision)
	if c.result != nil {
		return *c.result, c.err
	}
	result := models.ApprovalDecisionResult{ApprovalID: approvalID, Decision: "APPROVED", DecidedVia: "USER", Continuation: c.continuation}
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

	// Until the server's outcome arrives, the card keeps this client's decision.
	m, cmd = press(t, m, tea.KeyPressMsg{Code: 'n', Text: "n"})
	m = decide(t, m, cmd)
	m, _ = m.finishStream(nil)
	if got := approvalEntry(t, m, "a2"); got != "● Not approved: Create issue" || len(m.approvals) != 1 {
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

func TestStopLeavesTheOutcomeToTheServer(t *testing.T) {
	saved := waitingSession(t)
	// The Stop rejected the request.
	saved.Packets[0] = append(saved.Packets[0][:2], savedPacket(t, map[string]any{"type": "tool_approval_resolved", "approval_id": "a1", "outcome": "rejected"}))
	saved.ApprovalsVersion = "v2"
	client := &resumingClient{saved: saved}
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m.approvalsVersion = "v1"
	m = receive(t, m, ch, approvalRequest("a1"))
	for _, key := range []tea.KeyPressMsg{{Code: tea.KeyEscape}, {Code: 'c', Mod: tea.ModCtrl}} {
		cancelled := false
		m.streamCancel = func() { cancelled = true }
		m, _ = press(t, m, key)
		if !cancelled || !m.isStreaming {
			t.Fatalf("%s must request Stop and keep the turn until it settles", key.String())
		}
	}
	if got := approvalEntry(t, m, "a1"); !strings.HasPrefix(got, "● Approval requested: Create issue") {
		t.Fatalf("Stop marked the card before the server reported its outcome: %q", got)
	}

	// The cut stream drops the resolution; the status reports the version of
	// the saved rejection, and the session load shows it.
	updated, _ := m.Update(StreamDoneMsg{Channel: ch})
	updated, cmd := updated.(Model).Update(sessionReadyMsg{sessionID: waitingSessionID, channel: ch, status: models.ChatSessionStatus{ApprovalsVersion: "v2"}})
	m = updated.(Model)
	if m.isStreaming {
		t.Fatal("the stopped response keeps input blocked")
	}
	if got := approvalEntry(t, m, "a1"); !strings.HasPrefix(got, "● Approval requested: Create issue") {
		t.Fatalf("the end of the stream marked the card: %q", got)
	}
	for _, msg := range messages(t, cmd) {
		updated, _ = m.Update(msg)
		m = updated.(Model)
	}
	if got := approvalEntry(t, m, "a1"); got != "● Not approved: Create issue" || len(m.approvals) != 0 {
		t.Fatalf("record = %q, want the server's outcome", got)
	}
}

func TestEscAfterTheStopForDecisionsDoesNothing(t *testing.T) {
	client := &resumingClient{stops: make(chan int, 1)}
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: 2})
	m = receive(t, m, ch, approvalRequest("a1"))
	reason := models.StopReasonAwaitingApproval
	m = receive(t, m, ch, models.StopEvent{StopReason: &reason})
	// The stream has not closed yet.
	for _, key := range []tea.KeyPressMsg{{Code: tea.KeyEscape}, {Code: 'c', Mod: tea.ModCtrl}} {
		m.streamCancel = func() { t.Fatalf("%s cut the stream of a response that waits", key.String()) }
		m, _ = press(t, m, key)
	}
	if m.stopRequested || !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") {
		t.Fatalf("Esc acted on a response that waits:\n%s", approvalEntry(t, m, "a1"))
	}
	if strings.Contains(approvalEntry(t, m, "a1"), "esc stop the response") {
		t.Fatal("the card offers Stop for a response that waits")
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
	// requests records the stream and cursor of each resume.
	requests []resumeRequest
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

func (c *resumingClient) ResumeChatStream(_ context.Context, sessionID string, streamID *int, cursor int) <-chan models.StreamEvent {
	c.resumed = append(c.resumed, sessionID)
	c.requests = append(c.requests, resumeRequest{streamID, cursor})
	return c.running
}

func (c *resumingClient) StopChatSession(_ context.Context, _ string, streamID int) {
	c.stops <- streamID
}

const waitingSessionID = "11111111-2222-3333-4444-555555555555"

func savedPacket(t *testing.T, obj map[string]any) json.RawMessage {
	t.Helper()
	line, err := json.Marshal(map[string]any{"placement": map[string]any{"turn_index": 0}, "obj": obj})
	if err != nil {
		t.Fatal(err)
	}
	return line
}

// messages runs cmd, and each command of a batch, and returns their messages.
func messages(t *testing.T, cmd tea.Cmd) []tea.Msg {
	t.Helper()
	if cmd == nil {
		return nil
	}
	msg := cmd()
	batch, ok := msg.(tea.BatchMsg)
	if !ok {
		return []tea.Msg{msg}
	}
	var all []tea.Msg
	for _, each := range batch {
		all = append(all, messages(t, each)...)
	}
	return all
}

// waitingSession is a saved session whose response 2 waits for a1.
func waitingSession(t *testing.T) *models.ChatSessionDetailResponse {
	t.Helper()
	packet := func(obj map[string]any) json.RawMessage { return savedPacket(t, obj) }
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
	client := &resumingClient{sent: make(chan models.StreamEvent, 1), saved: waitingSession(t)}
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m.viewport.startAgent()
	m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: 2})
	m = receive(t, m, ch, models.MessageDeltaEvent{Content: "Filing the ticket."})
	m, _ = m.finishStream(nil)

	// The client does not check for waiting requests; the server rejects the message.
	m, cmd := m.sendMessage("follow-up")
	if cmd == nil {
		t.Fatal("the message was not sent")
	}
	m.input.textInput.SetValue("")
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

	// The session load shows the request that waits.
	close(client.sent)
	for _, msg := range messages(t, cmd) {
		updated, _ = m.Update(msg)
		m = updated.(Model)
	}
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
	if !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") {
		t.Fatal("the waiting request cannot be decided")
	}
}

// stoppedForDecisions is a chat whose response 2 stopped its stream to wait
// for a1 and a2.
func stoppedForDecisions(t *testing.T, client api.ClientAPI) Model {
	t.Helper()
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m.viewport.startAgent()
	m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: 2})
	m = receive(t, m, ch, models.MessageDeltaEvent{Content: "Filing the ticket."})
	m = receive(t, m, ch, approvalRequest("a1"))
	m = receive(t, m, ch, approvalRequest("a2"))
	reason := models.StopReasonAwaitingApproval
	m = receive(t, m, ch, models.StopEvent{StopReason: &reason})
	updated, _ := m.Update(StreamDoneMsg{Channel: ch})
	updated, _ = updated.(Model).Update(sessionReadyMsg{sessionID: waitingSessionID, channel: ch})
	return updated.(Model)
}

func TestDecisionsFollowTheContinuationThatTheServerNames(t *testing.T) {
	client := &resumingClient{running: make(chan models.StreamEvent, 8)}
	m := stoppedForDecisions(t, client)
	if m.isStreaming || m.activeApproval() != 0 {
		t.Fatal("the cards are not actionable after the stream stopped")
	}

	// a2 still waits, so the server names no continuation, and the idle
	// session's saved state shows a2 waiting.
	saved := waitingSession(t)
	saved.Packets[0] = append(saved.Packets[0][:2],
		savedPacket(t, map[string]any{"type": "tool_approval_resolved", "approval_id": "a1", "outcome": "approved"}),
		savedPacket(t, map[string]any{"type": "tool_approval_request", "approval_id": "a2", "tool_name": "mcp__3__linear__create_issue", "display_name": "Create issue"}),
		savedPacket(t, map[string]any{"type": "stop", "stop_reason": "awaiting_approval"}))
	client.saved = saved
	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	m, follow := run(t, m, cmd)
	m, load := run(t, m, follow)
	m, _ = run(t, m, load)
	if m.isStreaming || len(m.approvals) != 1 || m.approvals[0].request.ApprovalID != "a2" || len(client.resumed) != 0 {
		t.Fatalf("the idle session's saved state does not show a2 waiting: %+v", m.approvals)
	}

	client.continuation = &models.ChatStream{StreamID: 3, ResponseIDs: []int{2}}
	m, cmd = press(t, m, tea.KeyPressMsg{Code: 'n', Text: "n"})
	m, _ = run(t, m, cmd)
	if len(client.requests) != 1 || *client.requests[0].streamID != 3 || client.requests[0].cursor != 0 || m.streamCh != client.running {
		t.Fatalf("requests = %+v, want stream 3 from cursor 0", client.requests)
	}
	// The continuation replays the response with the saved outcomes, then
	// sends the same outcomes again live.
	for _, event := range []models.StreamEvent{
		models.StreamCursorEvent{StreamID: 3},
		models.MessageIDEvent{ReservedAgentMessageID: 2},
		models.MessageDeltaEvent{Content: "Filing the ticket."},
		approvalRequest("a1"),
		models.ToolApprovalResolvedEvent{ApprovalID: "a1", Outcome: "approved"},
		approvalRequest("a2"),
		models.ToolApprovalResolvedEvent{ApprovalID: "a2", Outcome: "rejected"},
		models.ReplayEndEvent{},
	} {
		m = receive(t, m, client.running, event)
	}
	if m.activeApproval() >= 0 || m.streamID == nil || *m.streamID != 3 {
		t.Fatalf("the replay made a decided card actionable again or renamed the stream: %+v", m.streamID)
	}
	m = receive(t, m, client.running, models.ToolApprovalResolvedEvent{ApprovalID: "a1", Outcome: "approved"})
	m = receive(t, m, client.running, models.ToolApprovalResolvedEvent{ApprovalID: "a2", Outcome: "rejected"})
	m = receive(t, m, client.running, models.MessageDeltaEvent{Content: "Filed ENG-1."})
	view := stripANSI(m.viewport.view(40))
	if strings.Count(view, "Filing the ticket.") != 1 || !strings.Contains(view, "Filed ENG-1.") {
		t.Fatalf("the continuation does not replace the response:\n%s", view)
	}
	if strings.Count(view, "Approved: Create issue") != 1 || strings.Count(view, "Not approved: Create issue") != 1 || len(m.approvals) != 0 {
		t.Fatalf("the cards do not show the server's outcomes once:\n%s", view)
	}
}

func TestSessionGrantThatDecidesTheOtherRequestsFollowsTheContinuation(t *testing.T) {
	client := &resumingClient{running: make(chan models.StreamEvent, 8)}
	m := stoppedForDecisions(t, client)
	// The grant also approves a2 on the server, so the response continues.
	client.continuation = &models.ChatStream{StreamID: 3, ResponseIDs: []int{2}}
	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'a', Text: "a"})
	m, _ = run(t, m, cmd)
	if len(client.requests) != 1 || *client.requests[0].streamID != 3 {
		t.Fatalf("a decision that continued the response is not followed: %+v", client.requests)
	}
	m = receive(t, m, client.running, models.ToolApprovalResolvedEvent{ApprovalID: "a2", Outcome: "approved_for_chat"})
	if got := approvalEntry(t, m, "a2"); got != "● Approved for this session: Create issue" {
		t.Fatalf("a2 = %q, want the grant's outcome", got)
	}
}

func TestRootDecisionWithoutContinuationFollowsTheResponseAfterTheTurnThatHoldsTheChat(t *testing.T) {
	client := &pollingClient{
		resumingClient: &resumingClient{running: make(chan models.StreamEvent, 8)},
		statuses: []models.ChatSessionStatus{
			// Another model's resume holds the chat when the decisions land.
			{IsProcessing: true, CurrentStream: &models.ChatStream{StreamID: 4, ResponseIDs: []int{5}}},
			// Its release hands the chat to this response's resume.
			{IsProcessing: true},
			{IsProcessing: true, CurrentStream: &models.ChatStream{StreamID: 6, ResponseIDs: []int{2}}},
		},
	}
	m := stoppedForDecisions(t, client)
	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	m, _ = run(t, m, cmd)
	m, cmd = press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	m, follow := run(t, m, cmd)
	m, _ = run(t, m, follow)
	if len(client.requests) != 1 || *client.requests[0].streamID != 6 || client.requests[0].cursor != 0 || m.streamCh != client.running {
		t.Fatalf("requests = %+v, want stream 6 from cursor 0", client.requests)
	}
}

func TestDecisionThatAnotherClientMadeFollowsTheCurrentStream(t *testing.T) {
	client := &resumingClient{running: make(chan models.StreamEvent, 8)}
	m := stoppedForDecisions(t, client)
	client.err = &api.OnyxAPIError{StatusCode: 409, Detail: "already decided"}
	client.status = &models.ChatSessionStatus{IsProcessing: true, CurrentStream: &models.ChatStream{StreamID: 3, ResponseIDs: []int{2}}}
	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	m, read := run(t, m, cmd)
	if got := approvalEntry(t, m, "a1"); got != "● No longer waiting: Create issue" {
		t.Fatalf("record = %q", got)
	}
	m, _ = run(t, m, read)
	if len(client.requests) != 1 || *client.requests[0].streamID != 3 || client.requests[0].cursor != 0 || m.streamCh != client.running {
		t.Fatalf("requests = %+v, want stream 3 from cursor 0", client.requests)
	}
}

func TestResumingAWaitingSessionShowsItsRequestThatStopCannotEnd(t *testing.T) {
	client := &resumingClient{stops: make(chan int, 1)}
	m := NewModel(config.DefaultConfig(), client)
	m, _ = run(t, m, func() tea.Msg { return SessionResumedMsg{Detail: waitingSession(t)} })
	if !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") {
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
	if !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") {
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

func agentRequest(id string) models.ToolApprovalRequestEvent {
	request := approvalRequest(id)
	request.AgentName = "triage"
	return request
}

func TestAgentCardNeitherEndsWithTheResponseNorBlocksSends(t *testing.T) {
	client := &resumingClient{sent: make(chan models.StreamEvent)}
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m = receive(t, m, ch, agentRequest("b1"))
	card := approvalEntry(t, m, "b1")
	if !strings.Contains(card, "triage wants to run Create issue") || strings.Contains(card, "esc stop the response") {
		t.Fatalf("the agent card does not name its agent, or offers Stop for it:\n%s", card)
	}
	m.input.textInput.Focus()
	m.input.textInput.SetValue("next question")
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	for _, e := range m.viewport.entries {
		if strings.Contains(e.content, "Approve or reject the tool call first") {
			t.Fatal("an agent's request asks to be decided before the next message")
		}
	}
	m.input.textInput.SetValue("")

	m.streamCancel = func() {}
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyEscape})
	m, _ = m.finishStream(nil)
	if !strings.Contains(approvalEntry(t, m, "b1"), "> Approve once (y)") {
		t.Fatalf("Stop or the end of the response closed the agent card:\n%s", approvalEntry(t, m, "b1"))
	}
	if _, cmd := m.sendMessage("next question"); cmd == nil {
		t.Fatal("an agent's request blocked the next message")
	}
}

func TestApprovalsVersionChangeLoadsTheSessionCards(t *testing.T) {
	saved := waitingSession(t)
	request := map[string]any{"type": "tool_approval_request", "approval_id": "b1", "tool_name": "create_issue", "display_name": "Create issue", "agent_name": "triage"}
	saved.Packets[0] = []json.RawMessage{savedPacket(t, request)}
	saved.ApprovalsVersion = "v2"
	client := &resumingClient{saved: saved}
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m.approvalsVersion = "v1"
	updated, _ := m.Update(StreamDoneMsg{Channel: ch})
	updated, cmd := updated.(Model).Update(sessionReadyMsg{sessionID: waitingSessionID, channel: ch, status: models.ChatSessionStatus{ApprovalsVersion: "v2"}})
	m = updated.(Model)
	for _, msg := range messages(t, cmd) {
		updated, _ = m.Update(msg)
		m = updated.(Model)
	}
	if !strings.Contains(approvalEntry(t, m, "b1"), "triage wants to run Create issue") {
		t.Fatal("the agent's request does not show")
	}

	// The agent's request ends with no live resolution; the next version shows it.
	saved.Packets[0] = append(saved.Packets[0], savedPacket(t, map[string]any{"type": "tool_approval_resolved", "approval_id": "b1", "outcome": "cancelled"}))
	saved.ApprovalsVersion = "v3"
	ch = make(chan models.StreamEvent)
	m.streamCh, m.isStreaming = ch, true
	updated, _ = m.Update(StreamDoneMsg{Channel: ch})
	updated, cmd = updated.(Model).Update(sessionReadyMsg{sessionID: waitingSessionID, channel: ch, status: models.ChatSessionStatus{ApprovalsVersion: "v2"}})
	for _, msg := range messages(t, cmd) {
		if _, loaded := msg.(approvalsLoadedMsg); loaded {
			t.Fatal("an unchanged version loaded the session")
		}
	}
	m = updated.(Model)
	m.streamCh, m.isStreaming = ch, true
	updated, _ = m.Update(StreamDoneMsg{Channel: ch})
	updated, cmd = updated.(Model).Update(sessionReadyMsg{sessionID: waitingSessionID, channel: ch, status: models.ChatSessionStatus{ApprovalsVersion: "v3"}})
	m = updated.(Model)
	for _, msg := range messages(t, cmd) {
		updated, _ = m.Update(msg)
		m = updated.(Model)
	}
	if got := approvalEntry(t, m, "b1"); got != "● No longer waiting: Create issue" || len(m.approvals) != 0 {
		t.Fatalf("record = %q", got)
	}
}

func TestFailedApprovalsLoadIsRetried(t *testing.T) {
	saved := waitingSession(t)
	request := map[string]any{"type": "tool_approval_request", "approval_id": "b1", "tool_name": "create_issue", "display_name": "Create issue", "agent_name": "triage"}
	saved.Packets[0] = []json.RawMessage{savedPacket(t, request)}
	saved.ApprovalsVersion = "v2"
	m, _ := streamingModel(&resumingClient{saved: saved})
	session := waitingSessionID
	m.chatSessionID = &session
	m.approvalsVersion = "v1"
	status := models.ChatSessionStatus{ApprovalsVersion: "v2"}

	m, load := m.noteApprovalsVersion(status)
	if load == nil {
		t.Fatal("a new version did not load the session")
	}
	if _, again := m.noteApprovalsVersion(status); again != nil {
		t.Fatal("a status read loaded the session while its load ran")
	}
	updated, retry := m.Update(approvalsLoadedMsg{err: errors.New("offline")})
	m = updated.(Model)
	if retry == nil {
		t.Fatal("a failed load scheduled no status read")
	}
	m, load = m.noteApprovalsVersion(status)
	if load == nil {
		t.Fatal("a failed load kept the status read from loading the session again")
	}
	updated, _ = m.Update(load())
	m = updated.(Model)
	if !strings.Contains(approvalEntry(t, m, "b1"), "triage wants to run Create issue") || m.approvalsVersion != "v2" {
		t.Fatalf("the agent's request does not show; version = %q", m.approvalsVersion)
	}
}

// feedApprovalLoads feeds cmd's messages to m, and the session loads that
// they start, but not the status reads that follow them.
func feedApprovalLoads(t *testing.T, m Model, cmd tea.Cmd) Model {
	t.Helper()
	for _, msg := range messages(t, cmd) {
		updated, next := m.Update(msg)
		m = updated.(Model)
		if _, poll := msg.(approvalsPollMsg); !poll {
			continue
		}
		for _, loaded := range messages(t, next) {
			if _, ok := loaded.(approvalsLoadedMsg); ok {
				updated, _ = m.Update(loaded)
				m = updated.(Model)
			}
		}
	}
	return m
}

// agentWaitingClient reports a background agent whose request waits in
// approvals version v2.
func agentWaitingClient(t *testing.T) *resumingClient {
	t.Helper()
	saved := waitingSession(t)
	saved.Packets[0] = []json.RawMessage{savedPacket(t, map[string]any{"type": "tool_approval_request", "approval_id": "b1", "tool_name": "create_issue", "display_name": "Create issue", "agent_name": "triage"})}
	saved.ApprovalsVersion = "v2"
	return &resumingClient{saved: saved, status: &models.ChatSessionStatus{ApprovalsVersion: "v2", HasActiveSubagents: true}}
}

func TestAnswerThatEndsWithARunningAgentWatchesItsRequests(t *testing.T) {
	m, ch := streamingModel(agentWaitingClient(t))
	session := waitingSessionID
	m.chatSessionID = &session
	m = receive(t, m, ch, models.StopEvent{})
	updated, _ := m.Update(StreamDoneMsg{Channel: ch})
	updated, cmd := updated.(Model).Update(sessionReadyMsg{sessionID: waitingSessionID, channel: ch, status: models.ChatSessionStatus{HasActiveSubagents: true}})
	m = feedApprovalLoads(t, updated.(Model), cmd)
	if m.isStreaming || !strings.Contains(approvalEntry(t, m, "b1"), "triage wants to run Create issue") {
		t.Fatal("the running agent's later request does not show")
	}
}

func TestResumingAnIdleSessionWithARunningAgentWatchesItsRequests(t *testing.T) {
	client := agentWaitingClient(t)
	resumed := waitingSession(t)
	resumed.Packets[0] = resumed.Packets[0][:1]
	m := NewModel(config.DefaultConfig(), client)
	updated, cmd := m.Update(SessionResumedMsg{Detail: resumed, Status: models.ChatSessionStatus{HasActiveSubagents: true}})
	m = feedApprovalLoads(t, updated.(Model), cmd)
	if !strings.Contains(approvalEntry(t, m, "b1"), "triage wants to run Create issue") {
		t.Fatal("the running agent's later request does not show")
	}
}

func TestEarlierFollowCannotReplaceALaterContinuation(t *testing.T) {
	client := &resumingClient{running: make(chan models.StreamEvent, 8), stops: make(chan int, 1)}
	m := stoppedForDecisions(t, client)
	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	m, follow := run(t, m, cmd)
	// The first decision's status read finds the session idle, but its
	// result arrives after the second decision continued the response.
	stale := follow()
	client.continuation = &models.ChatStream{StreamID: 3, ResponseIDs: []int{2}}
	m, cmd = press(t, m, tea.KeyPressMsg{Code: 'n', Text: "n"})
	m, _ = run(t, m, cmd)
	updated, next := m.Update(stale)
	m = updated.(Model)
	if next != nil || m.reloading || !m.isStreaming || m.streamID == nil || *m.streamID != 3 {
		t.Fatalf("an earlier status read replaced the continuation: reloading=%v streaming=%v", m.reloading, m.isStreaming)
	}
	select {
	case stream := <-client.stops:
		t.Fatalf("stopped stream %d", stream)
	default:
	}
}

func TestEarlierFollowCannotReplaceANewMessage(t *testing.T) {
	client := &resumingClient{running: make(chan models.StreamEvent, 8), sent: make(chan models.StreamEvent, 8), stops: make(chan int, 1)}
	m := stoppedForDecisions(t, client)
	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	m, _ = run(t, m, cmd)
	m, cmd = press(t, m, tea.KeyPressMsg{Code: 'n', Text: "n"})
	m, follow := run(t, m, cmd)
	// The last decision's status read finds the session idle, but its
	// result arrives after the user sent another message.
	stale := follow()
	m, _ = m.sendMessage("next question")
	if !m.isStreaming || m.streamCh != client.sent {
		t.Fatal("the next message did not start")
	}
	updated, next := m.Update(stale)
	m = updated.(Model)
	if next != nil || m.reloading || !m.isStreaming || m.streamCh != client.sent {
		t.Fatalf("an earlier status read replaced the new message: reloading=%v streaming=%v", m.reloading, m.isStreaming)
	}
	select {
	case stream := <-client.stops:
		t.Fatalf("stopped stream %d", stream)
	default:
	}
}

func TestRootTurnThatAgentResultsStartIsFollowed(t *testing.T) {
	client := &pollingClient{
		resumingClient: &resumingClient{running: make(chan models.StreamEvent, 8)},
		statuses: []models.ChatSessionStatus{
			// The root's turn for the agent's result prepares, then streams.
			{IsProcessing: true},
			{IsProcessing: true, CurrentStream: &models.ChatStream{StreamID: 7, ResponseIDs: []int{9}}},
		},
	}
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m = receive(t, m, ch, models.StopEvent{})
	updated, _ := m.Update(StreamDoneMsg{Channel: ch})
	// A finished agent's unread result can start a turn; no agent is active.
	updated, cmd := updated.(Model).Update(sessionReadyMsg{sessionID: waitingSessionID, channel: ch, status: models.ChatSessionStatus{HasStartableInput: true}})
	m = updated.(Model)
	if m.isStreaming {
		t.Fatal("the answer did not finish")
	}
	m = runUntilStreaming(t, m, cmd)
	if len(client.requests) != 1 || *client.requests[0].streamID != 7 || client.requests[0].cursor != 0 || m.streamCh != client.running {
		t.Fatalf("requests = %+v, want stream 7 from cursor 0", client.requests)
	}
}

func TestReplyThatEndsBetweenStatusReadsShows(t *testing.T) {
	latest := 9
	saved := waitingSession(t)
	saved.Messages = append(saved.Messages, models.ChatMessageDetail{MessageID: latest, MessageType: "assistant", Message: "The agent filed ENG-1."})
	saved.Packets = [][]json.RawMessage{saved.Packets[0][:1], {}}
	client := &pollingClient{
		resumingClient: &resumingClient{},
		// The agent ran, and its follow-up reply ended before the next read.
		statuses: []models.ChatSessionStatus{{LatestResponseID: &latest}},
		sessions: map[string]*models.ChatSessionDetailResponse{"": saved},
	}
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m.viewport.startAgent()
	m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: 2})
	m = receive(t, m, ch, models.MessageDeltaEvent{Content: "Filing the ticket."})
	m = receive(t, m, ch, models.StopEvent{})
	updated, _ := m.Update(StreamDoneMsg{Channel: ch})
	updated, cmd := updated.(Model).Update(sessionReadyMsg{sessionID: waitingSessionID, channel: ch, status: models.ChatSessionStatus{HasActiveSubagents: true}})
	m = updated.(Model)
	pending := []tea.Cmd{cmd}
	for len(pending) > 0 {
		next := pending[0]
		pending = pending[1:]
		for _, msg := range messages(t, next) {
			updated, follow := m.Update(msg)
			m = updated.(Model)
			if follow != nil {
				pending = append(pending, follow)
			}
		}
	}
	if view := stripANSI(m.viewport.view(60)); !strings.Contains(view, "The agent filed ENG-1.") {
		t.Fatalf("the finished reply does not show:\n%s", view)
	}
	if client.reads > 3 {
		t.Fatalf("reads = %d, want the reads to settle after the reload", client.reads)
	}
}

func TestContinuationIsNotFollowedAfterTheUserLeavesTheChat(t *testing.T) {
	client := &resumingClient{running: make(chan models.StreamEvent, 8)}
	m := stoppedForDecisions(t, client)
	client.continuation = &models.ChatStream{StreamID: 3, ResponseIDs: []int{2}}
	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'a', Text: "a"})
	m, _ = cmdNew(m)
	m, _ = run(t, m, cmd)
	if len(client.requests) != 0 || m.isStreaming {
		t.Fatalf("a new chat followed the old chat's response: %+v", client.requests)
	}
}

// pollingClient answers status reads in order, then repeats the last one. A
// session load shows the saved session of the last status's version.
type pollingClient struct {
	*resumingClient
	statuses []models.ChatSessionStatus
	sessions map[string]*models.ChatSessionDetailResponse
	reads    int
	version  string
}

func (c *pollingClient) ChatSessionStatus(context.Context, string) (models.ChatSessionStatus, error) {
	status := c.statuses[min(c.reads, len(c.statuses)-1)]
	c.reads++
	c.version = status.ApprovalsVersion
	return status, nil
}

func (c *pollingClient) GetChatSession(context.Context, string) (*models.ChatSessionDetailResponse, error) {
	return c.sessions[c.version], nil
}

// watchAgentDecision decides the agent card b1 of a resumed session and runs
// every command that the decision starts until none is left.
func watchAgentDecision(t *testing.T, client *pollingClient) Model {
	t.Helper()
	m := NewModel(config.DefaultConfig(), client)
	updated, _ := m.Update(SessionResumedMsg{Detail: client.sessions["v1"], Status: models.ChatSessionStatus{ApprovalsVersion: "v0"}})
	m = updated.(Model)
	if m.approvalsVersion != "v1" {
		t.Fatalf("baseline = %q, want the session load's version", m.approvalsVersion)
	}
	// The decision continues the agent without a stream.
	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'y', Text: "y"})
	m, cmd = run(t, m, cmd)
	if got := approvalEntry(t, m, "b1"); got != "● Approved: Create issue" {
		t.Fatalf("b1 = %q, want the local decided state", got)
	}
	pending := []tea.Cmd{cmd}
	for len(pending) > 0 {
		next := pending[0]
		pending = pending[1:]
		for _, msg := range messages(t, next) {
			updated, follow := m.Update(msg)
			m = updated.(Model)
			if follow != nil {
				pending = append(pending, follow)
			}
		}
	}
	return m
}

func agentSession(t *testing.T, version string, packets ...map[string]any) *models.ChatSessionDetailResponse {
	t.Helper()
	saved := &models.ChatSessionDetailResponse{ChatSessionID: waitingSessionID, ApprovalsVersion: version, Packets: [][]json.RawMessage{{}}}
	for _, obj := range packets {
		saved.Packets[0] = append(saved.Packets[0], savedPacket(t, obj))
	}
	return saved
}

func agentAsks(id string) map[string]any {
	return map[string]any{"type": "tool_approval_request", "approval_id": id, "tool_name": "create_issue", "display_name": "Create issue", "agent_name": "triage"}
}

func TestAgentDecisionReadsTheStatusUntilItsCardResolves(t *testing.T) {
	resolved := map[string]any{"type": "tool_approval_resolved", "approval_id": "b1", "outcome": "approved"}
	client := &pollingClient{
		resumingClient: &resumingClient{},
		statuses:       []models.ChatSessionStatus{{ApprovalsVersion: "v1"}, {ApprovalsVersion: "v2"}},
		sessions: map[string]*models.ChatSessionDetailResponse{
			"v1": agentSession(t, "v1", agentAsks("b1")),
			"v2": agentSession(t, "v2", agentAsks("b1"), resolved),
		},
	}
	m := watchAgentDecision(t, client)
	// The read after the load that resolves the card is the last one.
	if client.reads != 3 || len(m.approvals) != 0 {
		t.Fatalf("reads = %d, want reads until the card resolves; cards = %d", client.reads, len(m.approvals))
	}
}

func TestAgentDecisionPollsWhileTheAgentRuns(t *testing.T) {
	resolved := map[string]any{"type": "tool_approval_resolved", "approval_id": "b1", "outcome": "approved"}
	client := &pollingClient{
		resumingClient: &resumingClient{},
		statuses: []models.ChatSessionStatus{
			// The decided agent counts as active before its host starts.
			{ApprovalsVersion: "v2", HasActiveSubagents: true},
			// The resumed agent asks again, then waits for that decision.
			{ApprovalsVersion: "v3", HasActiveSubagents: true},
			{ApprovalsVersion: "v3"},
			// Another client rejects the later request.
			{ApprovalsVersion: "v4"},
		},
		sessions: map[string]*models.ChatSessionDetailResponse{
			"v1": agentSession(t, "v1", agentAsks("b1")),
			"v2": agentSession(t, "v2", agentAsks("b1"), resolved),
			"v3": agentSession(t, "v3", agentAsks("b1"), resolved, agentAsks("b2")),
			"v4": agentSession(t, "v4", agentAsks("b1"), resolved, agentAsks("b2"),
				map[string]any{"type": "tool_approval_resolved", "approval_id": "b2", "outcome": "rejected"}),
		},
	}
	m := watchAgentDecision(t, client)
	if client.reads != 5 {
		t.Fatalf("reads = %d, want reads while an agent is active or a card waits", client.reads)
	}
	if got := approvalEntry(t, m, "b1"); got != "● Approved: Create issue" {
		t.Fatalf("b1 = %q, want the server's outcome", got)
	}
	if got := approvalEntry(t, m, "b2"); got != "● Not approved: Create issue" || len(m.approvals) != 0 || m.approvalsVersion != "v4" {
		t.Fatalf("b2 = %q, want the other client's outcome", got)
	}
}

// rootDecidedElsewhere answers status reads as if another client decided
// a1 and a2 of response 2, which prepares its continuation and then
// continues on stream 3.
func rootDecidedElsewhere(t *testing.T) *pollingClient {
	t.Helper()
	decided := waitingSession(t)
	decided.Packets[0] = append(decided.Packets[0][:2],
		savedPacket(t, map[string]any{"type": "tool_approval_resolved", "approval_id": "a1", "outcome": "approved"}),
		savedPacket(t, map[string]any{"type": "tool_approval_request", "approval_id": "a2", "tool_name": "mcp__3__linear__create_issue", "display_name": "Create issue"}),
		savedPacket(t, map[string]any{"type": "tool_approval_resolved", "approval_id": "a2", "outcome": "approved"}))
	decided.ApprovalsVersion = "v2"
	return &pollingClient{
		resumingClient: &resumingClient{running: make(chan models.StreamEvent, 8)},
		statuses: []models.ChatSessionStatus{
			{ApprovalsVersion: "v2", IsProcessing: true},
			{ApprovalsVersion: "v2", IsProcessing: true, CurrentStream: &models.ChatStream{StreamID: 3, ResponseIDs: []int{2}}},
		},
		sessions: map[string]*models.ChatSessionDetailResponse{"v2": decided},
	}
}

// runUntilStreaming feeds cmd's messages, and the commands they start, until
// the model streams.
func runUntilStreaming(t *testing.T, m Model, cmd tea.Cmd) Model {
	t.Helper()
	pending := []tea.Cmd{cmd}
	for len(pending) > 0 && !m.isStreaming {
		next := pending[0]
		pending = pending[1:]
		for _, msg := range messages(t, next) {
			updated, follow := m.Update(msg)
			m = updated.(Model)
			if follow != nil {
				pending = append(pending, follow)
			}
		}
	}
	return m
}

func TestRootRequestsDecidedElsewhereFollowTheContinuation(t *testing.T) {
	client := rootDecidedElsewhere(t)
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m.viewport.startAgent()
	m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: 2})
	m = receive(t, m, ch, approvalRequest("a1"))
	m = receive(t, m, ch, approvalRequest("a2"))
	reason := models.StopReasonAwaitingApproval
	m = receive(t, m, ch, models.StopEvent{StopReason: &reason})
	updated, _ := m.Update(StreamDoneMsg{Channel: ch})
	updated, cmd := updated.(Model).Update(sessionReadyMsg{sessionID: waitingSessionID, channel: ch})
	m = runUntilStreaming(t, updated.(Model), cmd)
	if len(m.approvals) != 0 || len(client.requests) != 1 || *client.requests[0].streamID != 3 || m.streamCh != client.running {
		t.Fatalf("cards = %d, requests = %+v, want stream 3 followed", len(m.approvals), client.requests)
	}
}

func TestResumedRootRequestDecidedElsewhereFollowsTheContinuation(t *testing.T) {
	client := rootDecidedElsewhere(t)
	m := NewModel(config.DefaultConfig(), client)
	updated, cmd := m.Update(SessionResumedMsg{Detail: waitingSession(t)})
	m = runUntilStreaming(t, updated.(Model), cmd)
	if len(m.approvals) != 0 || len(client.requests) != 1 || *client.requests[0].streamID != 3 || m.streamCh != client.running {
		t.Fatalf("cards = %d, requests = %+v, want stream 3 followed", len(m.approvals), client.requests)
	}
}
