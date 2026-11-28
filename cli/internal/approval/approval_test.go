package approval

import (
	"fmt"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

func TestArgumentsStripHostileContent(t *testing.T) {
	lines := Arguments(map[string]any{
		"cmd\x1b[2J":   "rm -rf /\x1b]52;c;ZWNobyBoaQ==\x07\nsecond line\rhidden",
		"link":         "\x1b]8;;https://evil\x1b\\click\x1b]8;;\x1b\\",
		"nested":       map[string]any{"k": "\x1b[31mred"},
		"long":         strings.Repeat("x", 500),
		"\u009bc1 key": 1,
	})
	joined := strings.Join(lines, "\n")
	if strings.ContainsAny(joined, "\x1b\x07\r\u009b") {
		t.Fatalf("arguments keep control characters: %q", joined)
	}
	if len(lines) != 5 {
		t.Fatalf("one line per argument expected, got %d: %q", len(lines), lines)
	}
	want := map[int]string{
		0: "cmd: rm -rf / second linehidden",
		1: "link: click",
		3: `nested: {"k":"\u001b[31mred"}`,
		4: "c1 key: 1",
	}
	for i, w := range want {
		if lines[i] != w {
			t.Errorf("line %d = %q, want %q", i, lines[i], w)
		}
	}
	if !strings.HasPrefix(lines[2], "long: ") || len([]rune(lines[2])) != len("long: ")+maxValueRunes || !strings.HasSuffix(lines[2], "…") {
		t.Errorf("long value not truncated: %q", lines[2])
	}
}

func TestArgumentsCapCount(t *testing.T) {
	args := map[string]any{}
	for i := range maxArguments + 3 {
		args[fmt.Sprintf("k%02d", i)] = i
	}
	lines := Arguments(args)
	if len(lines) != maxArguments+1 || lines[maxArguments] != "… 3 more" {
		t.Fatalf("lines = %q", lines)
	}
}

func TestAllArgumentsShowEveryValueInFull(t *testing.T) {
	args := map[string]any{
		"body":   "Hi,\n\tsee \x1b]8;;https://evil\x1b\\this\x1b]8;;\x1b\\\rnow",
		"nested": map[string]any{"k": 1},
	}
	long := strings.Repeat("x", 500)
	for i := range maxArguments + 3 {
		args[fmt.Sprintf("k%02d", i)] = long
	}
	lines := AllArguments(args)
	joined := strings.Join(lines, "\n")
	if strings.ContainsAny(joined, "\x1b\x07\r") {
		t.Fatalf("arguments keep control characters: %q", joined)
	}
	if lines[0] != "body: Hi," || lines[1] != "      see thisnow" {
		t.Fatalf("multi-line value = %q", lines[:2])
	}
	if len(lines) != 2+maxArguments+3+1 || lines[2] != "k00: "+long || lines[len(lines)-2] != "k12: "+long {
		t.Fatalf("an argument or value is cut: %q", lines)
	}
	if lines[len(lines)-1] != `nested: {"k":1}` {
		t.Fatalf("last line = %q", lines[len(lines)-1])
	}
}

func TestTitleFallsBack(t *testing.T) {
	if got := Title(models.ToolApprovalRequestEvent{DisplayName: "Create\x1b[2J issue\n"}); got != "Create issue " {
		t.Errorf("Title = %q", got)
	}
	if got := Title(models.ToolApprovalRequestEvent{ToolName: "create_issue"}); got != "create_issue" {
		t.Errorf("Title = %q", got)
	}
	if got := Title(models.ToolApprovalRequestEvent{DisplayName: "\x1b[2J"}); got != "Tool call" {
		t.Errorf("Title = %q", got)
	}
}

func TestAgentRequestNamesTheAgent(t *testing.T) {
	req := models.ToolApprovalRequestEvent{ToolName: "create_issue", DisplayName: "Create issue"}
	if got := AgentRequest(req); got != "" {
		t.Fatalf("the chat's own request names an agent: %q", got)
	}
	req.AgentName = "triage\x1b]52;c;ZWNobyBoaQ==\x07"
	if got := AgentRequest(req); got != "triage wants to run Create issue" {
		t.Fatalf("AgentRequest = %q", got)
	}
}

func TestOutcomeLabelNamesACommandGrant(t *testing.T) {
	if got := OutcomeLabel(models.ApprovalOutcomeApprovedForCommand); got != "Approved for this command" {
		t.Fatalf("OutcomeLabel = %q", got)
	}
}

func TestDecisionOutcomeNamesACommandGrant(t *testing.T) {
	result := models.ApprovalDecisionResult{Decision: "APPROVED", DecidedVia: "COMMAND_GRANT"}
	if got := DecisionOutcome(result); got != models.ApprovalOutcomeApprovedForCommand {
		t.Fatalf("DecisionOutcome = %q", got)
	}
}

func TestWiderApprovalFollowsTheServer(t *testing.T) {
	no := false
	tests := []struct {
		name     string
		req      models.ToolApprovalRequestEvent
		decision models.ApprovalDecision
		label    string
		ok       bool
	}{
		{"chat", models.ToolApprovalRequestEvent{}, models.ApproveSession, "Approve for this chat", true},
		{"asks each time", models.ToolApprovalRequestEvent{CanApproveForChat: &no}, "", "", false},
		{"command", models.ToolApprovalRequestEvent{CanApproveForChat: &no, CanApproveForCommand: true}, models.ApproveCommand, "Approve for this command", true},
	}
	for _, tt := range tests {
		decision, label, ok := WiderApproval(tt.req)
		if decision != tt.decision || label != tt.label || ok != tt.ok {
			t.Errorf("%s: WiderApproval = %q, %q, %v", tt.name, decision, label, ok)
		}
	}
}

func TestTitleNamesTheAppAndDeadlineReadsServerTimes(t *testing.T) {
	req := models.ToolApprovalRequestEvent{DisplayName: "GET /mail", AppName: "Gmail\x1b[2J"}
	if got := Title(req); got != "GET /mail in Gmail" {
		t.Fatalf("Title = %q", got)
	}
	for _, at := range []string{"2026-01-02T15:04:05Z", "2026-01-02T15:04:05.123456+00:00", "2026-01-02T15:04:05.123456"} {
		req.ExpiresAt = at
		if got := Deadline(req); !strings.HasPrefix(got, "Approve by ") {
			t.Errorf("Deadline(%q) = %q", at, got)
		}
	}
	req.ExpiresAt = "soon"
	if got := Deadline(req); got != "" {
		t.Errorf("Deadline of a bad time = %q", got)
	}
}
