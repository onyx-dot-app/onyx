package tui

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

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
	expires := time.Now().Add(10 * time.Minute)
	return models.ToolApprovalRequestEvent{
		ApprovalID:  id,
		ToolName:    "mcp__3__linear__create_issue",
		DisplayName: "Create issue",
		Arguments:   map[string]any{"title": "Bug"},
		ExpiresAt:   &expires,
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
			for _, want := range []string{"Approval requested: Create issue", "title: Bug", "Approve by", "> Approve once (y)", "Reject (n)"} {
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
		"expired":           "Timed out",
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
	m, _ = m.finishStream(nil)
	if got := approvalEntry(t, m, "a1"); got != "● No longer waiting: Create issue" || len(m.approvals) != 0 {
		t.Fatalf("finished stream left a waiting card: %q", got)
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
}

func (c *resumingClient) SendMessageStream(context.Context, string, *string, int, *int, []models.FileDescriptorPayload, *models.LLMOverride) <-chan models.StreamEvent {
	return c.sent
}

func (c *resumingClient) ResumeChatStream(_ context.Context, sessionID string) <-chan models.StreamEvent {
	c.resumed = append(c.resumed, sessionID)
	return c.running
}

func TestApprovalPendingErrorReattachesAndKeepsDraft(t *testing.T) {
	client := &resumingClient{running: make(chan models.StreamEvent)}
	m, ch := streamingModel(client)
	session := "session-1"
	m.chatSessionID = &session
	m.submittedMessage = "follow-up"

	m = receive(t, m, ch, models.ErrorEvent{Error: "HTTP 409: Approve or reject", StatusCode: 409, ErrorCode: api.ErrorCodeApprovalPending})

	var warning string
	for _, e := range m.viewport.entries {
		if e.kind == entryError {
			warning = e.content
		}
	}
	if !strings.Contains(warning, "waits for approval") || strings.Contains(warning, "409") {
		t.Fatalf("message = %q", warning)
	}
	if m.input.textInput.Value() != "follow-up" {
		t.Fatal("lost the draft")
	}
	if len(client.resumed) != 1 || client.resumed[0] != session || m.streamCh != client.running || !m.isStreaming {
		t.Fatalf("did not follow the running response: resumed=%v", client.resumed)
	}
	// The waiting request arrives on the resumed stream.
	m = receive(t, m, client.running, approvalRequest("a1"))
	if !strings.Contains(approvalEntry(t, m, "a1"), "> Approve once (y)") {
		t.Fatal("the waiting request cannot be decided")
	}
}

func TestApprovalPendingReplayReplacesTheShownResponse(t *testing.T) {
	client := &resumingClient{running: make(chan models.StreamEvent), sent: make(chan models.StreamEvent)}
	m, ch := streamingModel(client)
	session := "session-1"
	m.chatSessionID = &session
	m.viewport.startAgent()
	// The response waits for approval when its stream drops.
	m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: 7})
	m = receive(t, m, ch, models.MessageDeltaEvent{Content: "Filing the ticket."})
	m = receive(t, m, ch, approvalRequest("a1"))
	m, _ = m.finishStream(nil)

	m, _ = m.sendMessage("follow-up")
	m = receive(t, m, client.sent, models.ErrorEvent{Error: "HTTP 409", StatusCode: 409, ErrorCode: api.ErrorCodeApprovalPending})
	for _, e := range m.viewport.entries {
		if e.kind == entryUser {
			t.Fatalf("the unsent message shows: %q", e.content)
		}
	}
	if m.input.textInput.Value() != "follow-up" {
		t.Fatal("lost the draft")
	}

	// The running response replays from its start.
	m = receive(t, m, client.running, models.MessageIDEvent{ReservedAgentMessageID: 7})
	m = receive(t, m, client.running, models.MessageDeltaEvent{Content: "Filing the ticket."})
	m = receive(t, m, client.running, approvalRequest("a1"))
	m, _ = m.finishStream(nil)
	shown, cards := 0, 0
	for _, e := range m.viewport.entries {
		shown += strings.Count(e.content, "Filing the ticket.")
		if e.kind == entryApproval {
			cards++
		}
	}
	if shown != 1 || cards != 1 {
		t.Fatalf("the response shows %d times and its request %d times", shown, cards)
	}
	if last := m.viewport.entries[len(m.viewport.entries)-1]; last.kind != entryAgent {
		t.Fatalf("the replayed response is not last: %q", last.content)
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
		Running: true,
	})
	m = updated.(Model)

	if len(client.resumed) != 1 || client.resumed[0] != "session-1" || !m.isStreaming {
		t.Fatalf("did not follow the running response: resumed=%v", client.resumed)
	}
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
