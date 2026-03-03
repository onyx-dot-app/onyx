package tui

import (
	"regexp"
	"strings"
	"testing"
)

// stripANSI removes ANSI escape sequences for test comparisons.
var ansiRegex = regexp.MustCompile(`\x1b\[[0-9;]*m`)

func stripANSI(s string) string {
	return ansiRegex.ReplaceAllString(s, "")
}

func TestAddUserMessage(t *testing.T) {
	v := newViewport(80)
	v.addUserMessage("hello world")

	if len(v.entries) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(v.entries))
	}
	e := v.entries[0]
	if e.kind != entryUser {
		t.Errorf("expected entryUser, got %d", e.kind)
	}
	if e.content != "hello world" {
		t.Errorf("expected content 'hello world', got %q", e.content)
	}
	plain := stripANSI(e.rendered)
	if !strings.Contains(plain, "❯") {
		t.Errorf("expected rendered to contain ❯, got %q", plain)
	}
	if !strings.Contains(plain, "hello world") {
		t.Errorf("expected rendered to contain message text, got %q", plain)
	}
}

func TestStartAndFinishAgent(t *testing.T) {
	v := newViewport(80)
	v.startAgent()

	if !v.streaming {
		t.Error("expected streaming to be true after startAgent")
	}
	if len(v.entries) != 1 {
		t.Fatalf("expected 1 spacer entry, got %d", len(v.entries))
	}
	if v.entries[0].rendered != "" {
		t.Errorf("expected empty spacer, got %q", v.entries[0].rendered)
	}

	v.appendToken("Hello ")
	v.appendToken("world")

	if v.streamBuf != "Hello world" {
		t.Errorf("expected streamBuf 'Hello world', got %q", v.streamBuf)
	}

	v.finishAgent()

	if v.streaming {
		t.Error("expected streaming to be false after finishAgent")
	}
	if v.streamBuf != "" {
		t.Errorf("expected empty streamBuf after finish, got %q", v.streamBuf)
	}
	if len(v.entries) != 2 {
		t.Fatalf("expected 2 entries (spacer + agent), got %d", len(v.entries))
	}

	e := v.entries[1]
	if e.kind != entryAgent {
		t.Errorf("expected entryAgent, got %d", e.kind)
	}
	if e.content != "Hello world" {
		t.Errorf("expected content 'Hello world', got %q", e.content)
	}
	plain := stripANSI(e.rendered)
	if !strings.Contains(plain, "Hello world") {
		t.Errorf("expected rendered to contain message text, got %q", plain)
	}
}

func TestFinishAgentNoPadding(t *testing.T) {
	v := newViewport(80)
	v.startAgent()
	v.appendToken("Test message")
	v.finishAgent()

	e := v.entries[1]
	// First line should not start with plain spaces (ANSI codes are OK)
	plain := stripANSI(e.rendered)
	lines := strings.Split(plain, "\n")
	if strings.HasPrefix(lines[0], " ") {
		t.Errorf("first line should not start with spaces, got %q", lines[0])
	}
}

func TestFinishAgentMultiline(t *testing.T) {
	v := newViewport(80)
	v.startAgent()
	v.appendToken("Line one\n\nLine three")
	v.finishAgent()

	e := v.entries[1]
	plain := stripANSI(e.rendered)
	// Glamour may merge or reformat lines; just check content is present
	if !strings.Contains(plain, "Line one") {
		t.Errorf("expected 'Line one' in rendered, got %q", plain)
	}
	if !strings.Contains(plain, "Line three") {
		t.Errorf("expected 'Line three' in rendered, got %q", plain)
	}
}

func TestFinishAgentEmpty(t *testing.T) {
	v := newViewport(80)
	v.startAgent()
	v.finishAgent()

	if v.streaming {
		t.Error("expected streaming to be false")
	}
	if len(v.entries) != 1 {
		t.Errorf("expected 1 entry (spacer only), got %d", len(v.entries))
	}
}

func TestAddInfo(t *testing.T) {
	v := newViewport(80)
	v.addInfo("test info")

	if len(v.entries) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(v.entries))
	}
	e := v.entries[0]
	if e.kind != entryInfo {
		t.Errorf("expected entryInfo, got %d", e.kind)
	}
	plain := stripANSI(e.rendered)
	if strings.HasPrefix(plain, " ") {
		t.Errorf("info should not have leading spaces, got %q", plain)
	}
}

func TestAddError(t *testing.T) {
	v := newViewport(80)
	v.addError("something broke")

	if len(v.entries) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(v.entries))
	}
	e := v.entries[0]
	if e.kind != entryError {
		t.Errorf("expected entryError, got %d", e.kind)
	}
	plain := stripANSI(e.rendered)
	if !strings.Contains(plain, "something broke") {
		t.Errorf("expected error message in rendered, got %q", plain)
	}
}

func TestAddCitations(t *testing.T) {
	v := newViewport(80)
	v.addCitations(map[int]string{1: "doc-a", 2: "doc-b"})

	if len(v.entries) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(v.entries))
	}
	e := v.entries[0]
	if e.kind != entryCitation {
		t.Errorf("expected entryCitation, got %d", e.kind)
	}
	plain := stripANSI(e.rendered)
	if !strings.Contains(plain, "Sources (2)") {
		t.Errorf("expected sources count in rendered, got %q", plain)
	}
	if strings.HasPrefix(plain, " ") {
		t.Errorf("citation should not have leading spaces, got %q", plain)
	}
}

func TestAddCitationsEmpty(t *testing.T) {
	v := newViewport(80)
	v.addCitations(map[int]string{})

	if len(v.entries) != 0 {
		t.Errorf("expected no entries for empty citations, got %d", len(v.entries))
	}
}

func TestCitationVisibility(t *testing.T) {
	v := newViewport(80)
	v.addInfo("hello")
	v.addCitations(map[int]string{1: "doc"})

	v.showSources = false
	view := v.view(20)
	plain := stripANSI(view)
	if strings.Contains(plain, "Sources") {
		t.Error("expected citations hidden when showSources=false")
	}

	v.showSources = true
	view = v.view(20)
	plain = stripANSI(view)
	if !strings.Contains(plain, "Sources") {
		t.Error("expected citations visible when showSources=true")
	}
}

func TestClearAll(t *testing.T) {
	v := newViewport(80)
	v.addUserMessage("test")
	v.startAgent()
	v.appendToken("response")

	v.clearAll()

	if len(v.entries) != 0 {
		t.Errorf("expected no entries after clearAll, got %d", len(v.entries))
	}
	if v.streaming {
		t.Error("expected streaming=false after clearAll")
	}
	if v.streamBuf != "" {
		t.Errorf("expected empty streamBuf after clearAll, got %q", v.streamBuf)
	}
}

func TestClearDisplay(t *testing.T) {
	v := newViewport(80)
	v.addUserMessage("test")
	v.clearDisplay()

	if len(v.entries) != 0 {
		t.Errorf("expected no entries after clearDisplay, got %d", len(v.entries))
	}
}

func TestViewPadsShortContent(t *testing.T) {
	v := newViewport(80)
	v.addInfo("hello")

	view := v.view(10)
	lines := strings.Split(view, "\n")
	if len(lines) != 10 {
		t.Errorf("expected 10 lines (padded), got %d", len(lines))
	}
}

func TestViewTruncatesTallContent(t *testing.T) {
	v := newViewport(80)
	for i := 0; i < 20; i++ {
		v.addInfo("line")
	}

	view := v.view(5)
	lines := strings.Split(view, "\n")
	if len(lines) != 5 {
		t.Errorf("expected 5 lines (truncated), got %d", len(lines))
	}
}
