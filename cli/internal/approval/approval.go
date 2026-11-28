// Package approval formats tool approval requests for the terminal. Request
// fields come from the model, so every value passes through sanitize.
package approval

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/sanitize"
)

const (
	maxArguments  = 10
	maxKeyRunes   = 40
	maxValueRunes = 160

	// NoLongerWaiting records a request that ended without this client's decision.
	NoLongerWaiting = "No longer waiting"
)

// Title names the tool that waits for approval.
func Title(req models.ToolApprovalRequestEvent) string {
	title := "Tool call"
	for _, name := range []string{req.DisplayName, req.ToolName} {
		if name := truncate(sanitize.Line(name), maxKeyRunes); name != "" {
			title = name
			break
		}
	}
	if app := truncate(sanitize.Line(req.AppName), maxKeyRunes); app != "" {
		title += " in " + app
	}
	return title
}

// WiderApproval is the approval beyond this request that the server allows:
// for the rest of a VM command, or for the rest of the chat. ok is false when
// the action asks each time.
func WiderApproval(req models.ToolApprovalRequestEvent) (decision models.ApprovalDecision, label string, ok bool) {
	switch {
	case req.CanApproveForCommand:
		return models.ApproveCommand, "Approve for this command", true
	case req.CanApproveForChat != nil && !*req.CanApproveForChat:
		return "", "", false
	default:
		return models.ApproveSession, "Approve for this chat", true
	}
}

// Deadline is the local time by which the request needs a decision, or empty.
func Deadline(req models.ToolApprovalRequestEvent) string {
	if req.ExpiresAt == "" {
		return ""
	}
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.999999999"} {
		if at, err := time.Parse(layout, req.ExpiresAt); err == nil {
			return "Approve by " + at.Local().Format("15:04")
		}
	}
	return ""
}

// AgentRequest names the background agent that asks to run the tool, as the
// web card does. It is empty for the chat's own agent.
func AgentRequest(req models.ToolApprovalRequestEvent) string {
	agent := truncate(sanitize.Line(req.AgentName), maxKeyRunes)
	if agent == "" {
		return ""
	}
	return agent + " wants to run " + Title(req)
}

// Arguments returns one "key: value" line per argument, sorted by key.
// Long values and long argument lists are truncated; AllArguments shows them.
func Arguments(args map[string]any) []string {
	keys := sortedKeys(args)
	lines := make([]string, 0, min(len(keys), maxArguments+1))
	for i, key := range keys {
		if i == maxArguments {
			lines = append(lines, fmt.Sprintf("… %d more", len(keys)-maxArguments))
			break
		}
		lines = append(lines, truncate(sanitize.Line(key), maxKeyRunes)+": "+truncate(sanitize.Line(argumentText(args[key])), maxValueRunes))
	}
	return lines
}

// AllArguments returns every argument in full, sorted by key. A value keeps
// its line breaks, and its later lines are indented under its key.
func AllArguments(args map[string]any) []string {
	var lines []string
	for _, key := range sortedKeys(args) {
		value := strings.ReplaceAll(sanitize.Terminal(argumentText(args[key])), "\t", "    ")
		valueLines := strings.Split(value, "\n")
		lines = append(lines, sanitize.Line(key)+": "+valueLines[0])
		for _, line := range valueLines[1:] {
			lines = append(lines, "  "+line)
		}
	}
	return lines
}

func sortedKeys(args map[string]any) []string {
	keys := make([]string, 0, len(args))
	for key := range args {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

// argumentText is a string argument as is and any other value as JSON.
func argumentText(value any) string {
	if text, ok := value.(string); ok {
		return text
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		return "?"
	}
	return string(encoded)
}

// OutcomeLabel names how a request ended.
func OutcomeLabel(outcome string) string {
	switch outcome {
	case models.ApprovalOutcomeApproved:
		return "Approved"
	case models.ApprovalOutcomeApprovedForChat:
		return "Approved for this chat"
	case models.ApprovalOutcomeApprovedForCommand:
		return "Approved for this command"
	case models.ApprovalOutcomeRejected:
		return "Not approved"
	case models.ApprovalOutcomeDisabled:
		return "Disabled"
	default:
		return NoLongerWaiting
	}
}

// DecisionOutcome is the outcome of a request that the server decided as
// result reports.
func DecisionOutcome(result models.ApprovalDecisionResult) string {
	switch {
	case result.DecidedVia == "POLICY":
		return models.ApprovalOutcomeDisabled
	case result.Decision == "REJECTED":
		return models.ApprovalOutcomeRejected
	case result.DecidedVia == "SESSION_GRANT":
		return models.ApprovalOutcomeApprovedForChat
	case result.DecidedVia == "COMMAND_GRANT":
		return models.ApprovalOutcomeApprovedForCommand
	default:
		return models.ApprovalOutcomeApproved
	}
}

func truncate(s string, limit int) string {
	runes := []rune(s)
	if len(runes) <= limit {
		return s
	}
	return string(runes[:limit-1]) + "…"
}
