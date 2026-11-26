package tui

import (
	"bytes"
	"context"
	"errors"
	"maps"
	"slices"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/approval"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/parser"
	"github.com/onyx-dot-app/onyx/cli/internal/question"
)

// approvalCard is a tool approval request whose outcome the server has not
// reported yet.
type approvalCard struct {
	request models.ToolApprovalRequestEvent
	// responseID is the response that waits for the request, or 0 when
	// unknown.
	responseID int
	selected   int
	// sending is the decision in flight; empty while the user decides.
	sending models.ApprovalDecision
	// decided labels the outcome of this client's decision. The card shows it
	// until the server's resolution or a session load replaces it.
	decided string
	// expanded shows every argument in full instead of the compact list.
	expanded bool
}

var approvalActions = []struct {
	decision models.ApprovalDecision
	label    string
	key      string
}{
	{models.ApproveOnce, "Approve once", "y"},
	{models.ApproveSession, "Approve for this session", "a"},
	{models.RejectApproval, "Reject", "n"},
}

// approvalDecidedMsg carries the server's answer to a decision.
type approvalDecidedMsg struct {
	// sessionID is the chat that showed the request, or empty.
	sessionID  string
	approvalID string
	// responseID is the response that waits for the request.
	responseID int
	// agent marks a background agent's request.
	agent bool
	// streams is the model's stream count when the decision was sent.
	streams int
	result  models.ApprovalDecisionResult
	err     error
}

// renderApprovalCard renders a request. Only the active card, the oldest
// undecided one, takes input. stoppable offers Stop for the running response
// that waits for the request.
func renderApprovalCard(card approvalCard, active, stoppable bool, width int) string {
	if card.decided != "" {
		return approvalRecord(card.request, card.decided)
	}
	lines := []string{warnStyle.Render("● Approval requested: " + approval.Title(card.request))}
	if agent := approval.AgentRequest(card.request); agent != "" {
		lines = append(lines, dimInfoStyle.Render("    "+agent))
	}
	if card.expanded {
		// Wrap instead of truncating, so no part of a value is hidden.
		wrapAt := max(width-5, 16)
		for _, arg := range approval.AllArguments(card.request.Arguments) {
			for _, row := range strings.Split(ansi.Wrap(arg, wrapAt, ""), "\n") {
				lines = append(lines, "    "+row)
			}
		}
	} else {
		for _, arg := range approval.Arguments(card.request.Arguments) {
			lines = append(lines, "    "+arg)
		}
	}
	switch {
	case !active:
		lines = append(lines, dimInfoStyle.Render("    Waits for the request above."))
	case card.sending != "":
		for _, action := range approvalActions {
			if action.decision == card.sending {
				lines = append(lines, dimInfoStyle.Render("    Sending: "+action.label+"…"))
			}
		}
	default:
		selected := lipgloss.NewStyle().Foreground(accentColor).Bold(true)
		for i, action := range approvalActions {
			row := action.label + " (" + action.key + ")"
			if i == card.selected {
				lines = append(lines, "  "+selected.Render("> "+row))
			} else {
				lines = append(lines, "    "+row)
			}
		}
		details := "d show all"
		if card.expanded {
			details = "d show less"
		}
		hint := "    ↑↓ select • enter confirm • y/a/n • " + details
		if stoppable {
			hint += " • esc stop the response"
		}
		lines = append(lines, dimInfoStyle.Render(hint))
	}
	for i := range lines {
		lines[i] = ansi.Truncate(lines[i], max(width-1, 20), "…")
	}
	return strings.Join(lines, "\n")
}

// approvalRecord is the one-line record of how a request ended.
func approvalRecord(request models.ToolApprovalRequestEvent, label string) string {
	return infoStyle.Render("● " + label + ": " + approval.Title(request))
}

func (m Model) approvalIndex(approvalID string) int {
	for i, card := range m.approvals {
		if card.request.ApprovalID == approvalID {
			return i
		}
	}
	return -1
}

// activeApproval is the index of the oldest card that waits for this
// client's decision, or -1.
func (m Model) activeApproval() int {
	for i, card := range m.approvals {
		if card.decided == "" {
			return i
		}
	}
	return -1
}

// renderCards renders the approval and question cards.
func (m Model) renderCards() {
	active := m.activeApproval()
	// Stop ends the chat's running response, not a background agent.
	running := m.isStreaming && !m.awaitingUser
	for i, card := range m.approvals {
		stoppable := running && card.request.AgentName == ""
		m.viewport.setCard(card.request.ApprovalID, renderApprovalCard(card, i == active, stoppable, m.viewport.width))
	}
	m.renderQuestions()
}

// savedRequests is what the packets of a session load say about its
// approval requests and questions.
type savedRequests struct {
	approvals []approvalCard
	// outcomes holds the outcome of each ended approval request, by ID.
	outcomes  map[string]string
	questions []questionCard
	// answered holds the resolution of each ended question, by request ID.
	answered map[string]models.ToolQuestionResolvedEvent
}

// readSavedRequests reads the requests of a session load. The packets hold
// one list for each assistant message, in order.
func readSavedRequests(detail *models.ChatSessionDetailResponse) savedRequests {
	var responseIDs []int
	for _, message := range detail.Messages {
		if message.MessageType == "assistant" {
			responseIDs = append(responseIDs, message.MessageID)
		}
	}
	saved := savedRequests{outcomes: map[string]string{}, answered: map[string]models.ToolQuestionResolvedEvent{}}
	for i, packets := range detail.Packets {
		responseID := 0
		if i < len(responseIDs) {
			responseID = responseIDs[i]
		}
		for _, packet := range packets {
			if !bytes.Contains(packet, []byte("tool_approval_")) && !bytes.Contains(packet, []byte("tool_question_")) {
				continue
			}
			switch e := parser.ParseStreamLine(string(packet)).(type) {
			case models.ToolApprovalRequestEvent:
				saved.approvals = append(saved.approvals, approvalCard{request: e, responseID: responseID})
			case models.ToolApprovalResolvedEvent:
				saved.outcomes[e.ApprovalID] = e.Outcome
			case models.ToolQuestionRequestEvent:
				saved.questions = append(saved.questions, questionCard{request: e, responseID: responseID})
			case models.ToolQuestionResolvedEvent:
				saved.answered[e.QuestionRequestID] = e
			}
		}
	}
	return saved
}

// showSavedRequests shows the waiting approval requests and questions of a
// session load, including the requests of background agents, and the
// outcomes of shown requests. The load's approvals version becomes the
// version that the cards reflect.
func (m Model) showSavedRequests(approvalsVersion string, saved savedRequests) Model {
	m.approvalsVersion = approvalsVersion
	for _, card := range saved.questions {
		id := card.request.QuestionRequestID
		index := m.questionIndex(id)
		resolved, isResolved := saved.answered[id]
		switch {
		case isResolved && index >= 0:
			m = m.resolveQuestion(index, question.Outcome(card.request, resolved), resolved.Message)
		case !isResolved && index < 0 && !m.resolvedRequests[id]:
			m.questions = append(m.questions, card)
		}
	}
	for _, card := range saved.approvals {
		index := m.approvalIndex(card.request.ApprovalID)
		outcome, resolved := saved.outcomes[card.request.ApprovalID]
		switch {
		case resolved && index >= 0:
			m = m.resolveApproval(index, approval.OutcomeLabel(outcome))
		case !resolved && index < 0 && !m.resolvedRequests[card.request.ApprovalID]:
			m.approvals = append(m.approvals, card)
		}
	}
	m.renderCards()
	return m
}

// approvalsLoadedMsg carries a session load that shows the session's
// approval requests.
type approvalsLoadedMsg struct {
	detail *models.ChatSessionDetailResponse
	err    error
}

func loadApprovals(client api.ClientAPI, sessionID string) tea.Cmd {
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		detail, err := client.GetChatSession(ctx, sessionID)
		return approvalsLoadedMsg{detail, err}
	}
}

func (m Model) handleApprovalsLoaded(msg approvalsLoadedMsg) (tea.Model, tea.Cmd) {
	if m.chatSessionID == nil || (msg.err == nil && msg.detail.ChatSessionID != *m.chatSessionID) {
		return m, nil
	}
	m.approvalsLoadVersion = ""
	if msg.err != nil {
		// The cards keep their version, so a later status read loads again;
		// a status read follows a transient failure even when no agent runs.
		if api.IsRetryableReadinessError(msg.err) {
			m.approvalsPoll++
			return m, pollApprovals(m.client, *m.chatSessionID, m.approvalsPoll, api.StatusPollInterval)
		}
		return m, nil
	}
	// A root request that the load resolves was decided elsewhere; its
	// response continues on a stream that the status names.
	var waiting []approvalCard
	for _, card := range m.approvals {
		if card.request.AgentName == "" {
			waiting = append(waiting, card)
		}
	}
	asked := m.questions
	m = m.showSavedRequests(msg.detail.ApprovalsVersion, readSavedRequests(msg.detail))
	if m.isStreaming {
		return m, nil
	}
	for _, card := range waiting {
		if m.approvalIndex(card.request.ApprovalID) < 0 {
			return m.followResponse(*m.chatSessionID, card.responseID)
		}
	}
	for _, card := range asked {
		if m.questionIndex(card.request.QuestionRequestID) < 0 {
			return m.followResponse(*m.chatSessionID, card.responseID)
		}
	}
	return m, nil
}

// continuationMsg carries the stream that continues a decided response, or
// nil once the session is idle.
type continuationMsg struct {
	sessionID string
	follow    int
	stream    *models.ChatStream
	err       error
}

// handleContinuation follows the stream that continues a decided response.
// When none does, the saved session shows how the response went on.
func (m Model) handleContinuation(msg continuationMsg) (tea.Model, tea.Cmd) {
	if msg.follow != m.follow || m.chatSessionID == nil || msg.sessionID != *m.chatSessionID || errors.Is(msg.err, context.Canceled) {
		return m, nil
	}
	switch {
	case msg.err != nil:
		m.viewport.addError("Could not follow the response after the approval decision: " + msg.err.Error())
		return m, nil
	case msg.stream != nil:
		return m.followContinuation(*msg.stream)
	}
	if m.isStreaming {
		// The idle session ended the stream that this client still reads.
		m.reloading = true
		return cmdResume(m, msg.sessionID, m.streamCh)
	}
	return cmdReload(m, sessionReload{sessionID: msg.sessionID})
}

// noteApprovalsVersion loads the session's approval requests when a status
// reports a version that the shown cards do not reflect and no load of it
// runs. A successful load records its version.
func (m Model) noteApprovalsVersion(status models.ChatSessionStatus) (Model, tea.Cmd) {
	if status.ApprovalsVersion == m.approvalsVersion || status.ApprovalsVersion == m.approvalsLoadVersion || m.chatSessionID == nil {
		return m, nil
	}
	m.approvalsLoadVersion = status.ApprovalsVersion
	return m, loadApprovals(m.client, *m.chatSessionID)
}

// approvalsPollMsg carries a status read that follows a background agent's
// decision.
type approvalsPollMsg struct {
	sessionID string
	poll      int
	status    models.ChatSessionStatus
	err       error
}

func pollApprovals(client api.ClientAPI, sessionID string, poll int, delay time.Duration) tea.Cmd {
	return func() tea.Msg {
		time.Sleep(delay)
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		status, err := client.ChatSessionStatus(ctx, sessionID)
		return approvalsPollMsg{sessionID, poll, status, err}
	}
}

// handleApprovalsPoll loads the session cards when the approvals version
// changes, and follows a response that runs while no stream does, such as a
// root turn that agent results start. It reads again while watchesStatus.
func (m Model) handleApprovalsPoll(msg approvalsPollMsg) (tea.Model, tea.Cmd) {
	if msg.poll != m.approvalsPoll || m.chatSessionID == nil || msg.sessionID != *m.chatSessionID {
		return m, nil
	}
	if msg.err != nil {
		if api.IsRetryableReadinessError(msg.err) {
			return m, pollApprovals(m.client, msg.sessionID, msg.poll, api.StatusPollInterval)
		}
		return m, nil
	}
	m, load := m.noteApprovalsVersion(msg.status)
	var follow tea.Cmd
	if msg.status.CurrentStream != nil && !m.isStreaming {
		m, follow = m.followContinuation(*msg.status.CurrentStream)
	} else {
		m, follow = m.reloadUnseenResponse(msg.sessionID, msg.status)
	}
	if !m.watchesStatus(msg.status) {
		return m, tea.Batch(load, follow)
	}
	return m, tea.Batch(load, follow, pollApprovals(m.client, msg.sessionID, msg.poll, api.StatusPollInterval))
}

// watchesStatus reports whether status reads continue after status. Background
// agents' requests, decisions that other clients send, and turns that the
// server starts show only in status reads, so they continue while agents run
// or wait to resume, while a card waits or a session load runs, which can add
// one, and, without a stream, while a turn can start or a response prepares.
func (m Model) watchesStatus(status models.ChatSessionStatus) bool {
	return status.HasActiveSubagents || len(m.approvals) > 0 || len(m.questions) > 0 || m.approvalsLoadVersion != "" ||
		(!m.isStreaming && (status.HasStartableInput || status.IsProcessing))
}

// reloadUnseenResponse loads the saved session when a status read, while no
// stream runs, names a response that the chat does not show, such as an
// agent's follow-up reply that ended between reads.
func (m Model) reloadUnseenResponse(sessionID string, status models.ChatSessionStatus) (Model, tea.Cmd) {
	latest := status.LatestResponseID
	if m.isStreaming || latest == nil || *latest == m.reloadedResponseID || *latest == m.reloadingResponseID ||
		slices.ContainsFunc(m.viewport.entries, func(entry chatEntry) bool { return entry.responseID == *latest }) {
		return m, nil
	}
	m.reloadingResponseID = *latest
	return cmdReload(m, sessionReload{sessionID: sessionID, responseID: *latest})
}

// resolveApproval replaces a card with a one-line record of how it ended.
func (m Model) resolveApproval(index int, label string) Model {
	id := m.approvals[index].request.ApprovalID
	resolved := maps.Clone(m.resolvedRequests)
	if resolved == nil {
		resolved = map[string]bool{}
	}
	resolved[id] = true
	m.resolvedRequests = resolved
	m.viewport.setCard(id, approvalRecord(m.approvals[index].request, label))
	m.approvals = append(m.approvals[:index:index], m.approvals[index+1:]...)
	m.renderCards()
	return m
}

func (m Model) decideApproval(index int, decision models.ApprovalDecision) (Model, tea.Cmd) {
	m.approvals[index].sending = decision
	m.renderCards()
	client, approvalID := m.client, m.approvals[index].request.ApprovalID
	agent := m.approvals[index].request.AgentName != ""
	responseID := m.approvals[index].responseID
	streams := m.streams
	sessionID := ""
	if m.chatSessionID != nil {
		sessionID = *m.chatSessionID
	}
	return m, func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		result, err := client.DecideApproval(ctx, approvalID, decision)
		return approvalDecidedMsg{sessionID: sessionID, approvalID: approvalID, responseID: responseID, agent: agent, streams: streams, result: result, err: err}
	}
}

func (m Model) handleApprovalDecided(msg approvalDecidedMsg) (tea.Model, tea.Cmd) {
	noLongerWaiting := api.IsNoLongerWaiting(msg.err)
	// A card that the stream already resolved is gone.
	if index := m.approvalIndex(msg.approvalID); index >= 0 {
		m.approvals[index].sending = ""
		switch {
		case msg.err == nil:
			m.approvals[index].decided = approval.OutcomeLabel(approval.DecisionOutcome(msg.result))
		case noLongerWaiting:
			m.approvals[index].decided = approval.NoLongerWaiting
		default:
			m.viewport.addError("Could not send the approval decision: " + msg.err.Error())
		}
		m.renderCards()
	}
	return m.continueAfterAnswer(msg.sessionID, msg.responseID, msg.streams, msg.agent, msg.result.Continuation, msg.err)
}

// continueAfterAnswer follows the response after this client's decision or
// answer for responseID was sent from the chat sessionID while the model's
// stream count was streams: on the continuation that the server named, or on
// the stream that the status names.
func (m Model) continueAfterAnswer(sessionID string, responseID, streams int, agent bool, continuation *models.ChatStream, err error) (Model, tea.Cmd) {
	if m.chatSessionID == nil || sessionID != *m.chatSessionID {
		// The user left the chat that showed the request.
		return m, nil
	}
	if streams != m.streams {
		// A newer stream started, for example the continuation that a status
		// read followed, or the user's next message.
		return m, nil
	}
	switch {
	case err == nil && continuation != nil:
		return m.followContinuation(*continuation)
	case err == nil && agent:
		// A background agent continues without a stream, and its outcome and
		// later requests show only in a session load.
		m.approvalsPoll++
		return m, pollApprovals(m.client, sessionID, m.approvalsPoll, 0)
	case err != nil && !api.IsNoLongerWaiting(err):
		return m, nil
	}
	// The response continues on a stream that the status names: after
	// another client's answer, or after this answer once the turn that holds
	// the chat releases it.
	if m.isStreaming && !m.stopReceived && *m.parentMessageID == responseID {
		// The stream that this client reads writes the response.
		return m, nil
	}
	return m.followResponse(sessionID, responseID)
}

// followResponse reads the status until a stream continues the decided
// response, or until the idle session shows how it went on.
func (m Model) followResponse(sessionID string, responseID int) (Model, tea.Cmd) {
	if m.followCancel != nil {
		m.followCancel()
	}
	ctx, cancel := context.WithCancel(context.Background())
	m.followCancel = cancel
	m.follow++
	follow := m.follow
	client, streamID := m.client, 0
	if m.isStreaming && m.streamID != nil {
		streamID = *m.streamID
	}
	return m, func() tea.Msg {
		stream, err := api.FollowResponse(ctx, client, sessionID, responseID, streamID)
		return continuationMsg{sessionID, follow, stream, err}
	}
}

// followContinuation shows the response from the start of the stream that
// continues it, in place of its earlier display.
func (m Model) followContinuation(stream models.ChatStream) (Model, tea.Cmd) {
	if m.isStreaming && m.streamID != nil && *m.streamID == stream.StreamID {
		// An earlier decision's status read can no longer replace this stream.
		if m.followCancel != nil {
			m.followCancel()
		}
		m.follow++
		return m, nil
	}
	if m.isStreaming {
		m.viewport.finishAgent()
		m.viewport.endResponse()
	}
	m.viewport.startAgent()
	if len(stream.ResponseIDs) > 0 {
		m.viewport.showResponse(stream.ResponseIDs[0])
	}
	return m.followRunningResponse(&stream.StreamID)
}

// handleApprovalKey applies a key to the active card. It reports false for
// keys the card does not use, and for y/a/n/d/Enter while the input holds a
// draft, so the draft is never lost and typing never decides by accident.
func (m Model) handleApprovalKey(msg tea.KeyPressMsg) (Model, tea.Cmd, bool) {
	index := m.activeApproval()
	if index < 0 {
		return m, nil, false
	}
	card := &m.approvals[index]
	if card.sending != "" {
		return m, nil, false
	}
	key := msg.String()
	switch key {
	case "up", "down":
		if key == "up" && card.selected > 0 {
			card.selected--
		}
		if key == "down" && card.selected < len(approvalActions)-1 {
			card.selected++
		}
		m.renderCards()
		return m, nil, true
	}
	if m.input.textInput.Value() != "" {
		return m, nil, false
	}
	switch key {
	case "enter":
		m, cmd := m.decideApproval(index, approvalActions[card.selected].decision)
		return m, cmd, true
	case "d":
		card.expanded = !card.expanded
		m.renderCards()
		return m, nil, true
	}
	for _, action := range approvalActions {
		if key == action.key {
			m, cmd := m.decideApproval(index, action.decision)
			return m, cmd, true
		}
	}
	return m, nil, false
}
