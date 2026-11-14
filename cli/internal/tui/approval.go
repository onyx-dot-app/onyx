package tui

import (
	"context"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/approval"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

// approvalCard is a tool approval request whose outcome the server has not
// reported yet.
type approvalCard struct {
	request  models.ToolApprovalRequestEvent
	selected int
	// sending is the decision in flight; empty while the user decides.
	sending models.ApprovalDecision
	// decided labels the outcome of this client's decision. The card shows it
	// until the server reports the outcome, which replaces it.
	decided string
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
	approvalID string
	result     models.ApprovalDecisionResult
	err        error
}

// renderApprovalCard renders a request. Only the active card, the oldest
// undecided one, takes input.
func renderApprovalCard(card approvalCard, active bool, width int) string {
	if card.decided != "" {
		return approvalRecord(card.request, card.decided)
	}
	lines := []string{warnStyle.Render("● Approval requested: " + approval.Title(card.request))}
	for _, arg := range approval.Arguments(card.request.Arguments) {
		lines = append(lines, "    "+arg)
	}
	if deadline := approval.Deadline(card.request.ExpiresAt); deadline != "" {
		lines = append(lines, dimInfoStyle.Render("    "+deadline))
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
		lines = append(lines, dimInfoStyle.Render("    ↑↓ select • enter confirm • y/a/n • esc stop the response"))
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

func (m Model) renderApprovals() {
	active := m.activeApproval()
	for i, card := range m.approvals {
		m.viewport.setApproval(card.request.ApprovalID, renderApprovalCard(card, i == active, m.viewport.width))
	}
}

// resolveApproval replaces a card with a one-line record of how it ended.
func (m Model) resolveApproval(index int, label string) Model {
	m.viewport.setApproval(m.approvals[index].request.ApprovalID, approvalRecord(m.approvals[index].request, label))
	m.approvals = append(m.approvals[:index:index], m.approvals[index+1:]...)
	m.renderApprovals()
	return m
}

func (m Model) decideApproval(index int, decision models.ApprovalDecision) (Model, tea.Cmd) {
	m.approvals[index].sending = decision
	m.renderApprovals()
	client, approvalID := m.client, m.approvals[index].request.ApprovalID
	return m, func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		result, err := client.DecideApproval(ctx, approvalID, decision)
		return approvalDecidedMsg{approvalID: approvalID, result: result, err: err}
	}
}

func (m Model) handleApprovalDecided(msg approvalDecidedMsg) (tea.Model, tea.Cmd) {
	index := m.approvalIndex(msg.approvalID)
	if index < 0 {
		// The stream already reported how the request ended.
		return m, nil
	}
	m.approvals[index].sending = ""
	switch {
	case msg.err == nil:
		m.approvals[index].decided = approval.OutcomeLabel(approval.DecisionOutcome(msg.result))
	case api.IsApprovalNoLongerWaiting(msg.err):
		m.approvals[index].decided = approval.NoLongerWaiting
	default:
		m.viewport.addError("Could not send the approval decision: " + msg.err.Error())
	}
	m.renderApprovals()
	return m, nil
}

// handleApprovalKey applies a key to the active card. It reports false for
// keys the card does not use, and for y/a/n/Enter while the input holds a
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
		m.renderApprovals()
		return m, nil, true
	}
	if m.input.textInput.Value() != "" {
		return m, nil, false
	}
	if key == "enter" {
		m, cmd := m.decideApproval(index, approvalActions[card.selected].decision)
		return m, cmd, true
	}
	for _, action := range approvalActions {
		if key == action.key {
			m, cmd := m.decideApproval(index, action.decision)
			return m, cmd, true
		}
	}
	return m, nil, false
}
