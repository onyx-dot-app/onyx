// Package approval formats tool approval requests for the terminal. Request
// fields come from the model, so every value passes through sanitize.
package approval

import (
	"encoding/json"
	"fmt"
	"sort"
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
	for _, name := range []string{req.DisplayName, req.ToolName} {
		if title := truncate(sanitize.Line(name), maxKeyRunes); title != "" {
			return title
		}
	}
	return "Tool call"
}

// Arguments returns one "key: value" line per argument, sorted by key.
// Long values and long argument lists are truncated.
func Arguments(args map[string]any) []string {
	keys := make([]string, 0, len(args))
	for key := range args {
		keys = append(keys, key)
	}
	sort.Strings(keys)

	lines := make([]string, 0, min(len(keys), maxArguments+1))
	for i, key := range keys {
		if i == maxArguments {
			lines = append(lines, fmt.Sprintf("… %d more", len(keys)-maxArguments))
			break
		}
		value, ok := args[key].(string)
		if !ok {
			encoded, err := json.Marshal(args[key])
			if err != nil {
				encoded = []byte("?")
			}
			value = string(encoded)
		}
		lines = append(lines, truncate(sanitize.Line(key), maxKeyRunes)+": "+truncate(sanitize.Line(value), maxValueRunes))
	}
	return lines
}

// Deadline shows when the server ends the request, or "" when the server
// sent no deadline. Only the server decides that the request expired.
func Deadline(expiresAt *time.Time) string {
	if expiresAt == nil {
		return ""
	}
	return "Approve by " + expiresAt.Local().Format("15:04")
}

// OutcomeLabel names how a request ended.
func OutcomeLabel(outcome string) string {
	switch outcome {
	case models.ApprovalOutcomeApproved:
		return "Approved"
	case models.ApprovalOutcomeApprovedForChat:
		return "Approved for this session"
	case models.ApprovalOutcomeRejected:
		return "Not approved"
	case models.ApprovalOutcomeExpired:
		return "Timed out"
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
