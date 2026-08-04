package markdown

import (
	"strings"
	"testing"
)

func TestHighlightGo(t *testing.T) {
	// Indentation uses spaces: renderCode expands tabs before highlighting
	// (and lipgloss expands any stragglers at render time).
	code := "func main() {\n    // greet\n    fmt.Println(\"hello\", 42)\n}"
	lines, ok := highlightLines(code, "go")
	if !ok {
		t.Fatal("expected go to be supported")
	}
	if len(lines) != 4 {
		t.Fatalf("expected 4 lines, got %d: %q", len(lines), lines)
	}
	joined := strings.Join(lines, "\n")
	// Content must round-trip exactly (modulo a possible trailing newline);
	// only styling may change.
	if got := strings.TrimRight(stripANSI(joined), "\n"); got != code {
		t.Errorf("content changed by highlighting:\n%q\n%q", code, got)
	}
	distinct := map[string]bool{}
	for _, m := range ansiRegex.FindAllString(joined, -1) {
		distinct[m] = true
	}
	if len(distinct) < 4 {
		t.Errorf("expected several distinct token styles, got %d: %v", len(distinct), distinct)
	}
}

func TestHighlightPerLineStyling(t *testing.T) {
	// A multi-line construct (block comment) must not leak SGR state across
	// lines: every line must terminate its own styling.
	lines, ok := highlightLines("/* one\ntwo */", "go")
	if !ok {
		t.Fatal("expected go to be supported")
	}
	for i, l := range lines {
		if l != "" && !strings.HasSuffix(l, "m") {
			t.Errorf("line %d does not end with an SGR terminator: %q", i, l)
		}
	}
}

func TestAllVendoredLexersLoad(t *testing.T) {
	for _, path := range lexerFiles {
		name := strings.TrimSuffix(strings.TrimPrefix(path, "lexers/"), ".xml")
		if _, ok := highlightLines("x = 1", name); !ok {
			t.Errorf("lexer %q failed to load or tokenize", path)
		}
	}
	// Fence tags resolve via each definition's aliases and filename globs.
	for _, lang := range []string{
		"go", "golang", "py", "python3", "js", "ts", "yml", "sh", "shell",
		"rb", "rs", "cpp", "dockerfile", "make",
	} {
		if _, ok := highlightLines("x = 1", lang); !ok {
			t.Errorf("alias %q did not resolve to a lexer", lang)
		}
	}
}

func TestHighlightUnsupportedFallsBack(t *testing.T) {
	if _, ok := highlightLines("x", "brainfuck"); ok {
		t.Error("expected unsupported language to report ok=false")
	}
	if _, ok := highlightLines("x", ""); ok {
		t.Error("expected empty language to report ok=false")
	}
}

func TestFenceHighlightingIntegration(t *testing.T) {
	out := render(t, "```go\nfunc add(a int) int { return a + 1 }\n```", 80)
	plain := stripANSI(out)
	if !strings.Contains(plain, "func add(a int) int { return a + 1 }") {
		t.Fatalf("code content mangled: %q", plain)
	}
	distinct := map[string]bool{}
	for _, m := range ansiRegex.FindAllString(out, -1) {
		distinct[m] = true
	}
	if len(distinct) < 4 {
		t.Errorf("expected highlighted fence to use several styles, got %v", distinct)
	}

	// Unsupported language keeps the single dim code style.
	out = render(t, "```mystery\nabc def\n```", 80)
	if !strings.Contains(stripANSI(out), "abc def") {
		t.Errorf("fallback fence content missing: %q", stripANSI(out))
	}
}
