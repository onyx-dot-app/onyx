package approval

import (
	"fmt"
	"strings"
	"testing"
	"time"

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

func TestDeadlineShowsOnlyTheServerTime(t *testing.T) {
	past := time.Date(2000, 1, 1, 15, 45, 0, 0, time.Local)
	if got := Deadline(&past); got != "Approve by 15:45" {
		t.Errorf("Deadline = %q", got)
	}
	if got := Deadline(nil); got != "" {
		t.Errorf("Deadline = %q", got)
	}
}
