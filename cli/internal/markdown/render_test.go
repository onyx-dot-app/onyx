package markdown

import (
	"regexp"
	"strings"
	"testing"

	"github.com/charmbracelet/x/ansi"
)

var ansiRegex = regexp.MustCompile(`\x1b\[[0-9;]*m`)

func stripANSI(s string) string {
	return ansiRegex.ReplaceAllString(s, "")
}

func render(t *testing.T, md string, width int) string {
	t.Helper()
	return NewRenderer(width).Render(md)
}

func TestConstructs(t *testing.T) {
	tests := []struct {
		name    string
		md      string
		want    []string // substrings expected in ANSI-stripped output
		notWant []string // raw markdown syntax that must be consumed
	}{
		{
			name:    "headings",
			md:      "# Title\n\nbody\n\n###### Small",
			want:    []string{"Title", "body", "Small"},
			notWant: []string{"#"},
		},
		{
			name:    "emphasis",
			md:      "**bold *and italic* text** and ~~gone~~",
			want:    []string{"bold and italic text", "gone"},
			notWant: []string{"*", "~~"},
		},
		{
			name:    "inline code",
			md:      "run `go build ./...` now",
			want:    []string{"run go build ./... now"},
			notWant: []string{"`"},
		},
		{
			name: "inline code not reinterpreted",
			md:   "`a > b && **not bold**`",
			want: []string{"a > b && **not bold**"},
		},
		{
			name:    "fenced code with language",
			md:      "```go\nfunc main() {}\n```",
			want:    []string{"│ go", "│ func main() {}"},
			notWant: []string{"```"},
		},
		{
			name:    "unterminated fence mid-stream",
			md:      "```python\nx = 1\ny = 2\n",
			want:    []string{"│ python", "│ x = 1", "│ y = 2"},
			notWant: []string{"```"},
		},
		{
			name: "nested lists",
			md:   "- a\n  - b\n    - c\n- d",
			want: []string{"• a", "  • b", "    • c", "• d"},
		},
		{
			name: "ordered list start",
			md:   "5. five\n6. six",
			want: []string{"5. five", "6. six"},
		},
		{
			name: "task list",
			md:   "- [ ] todo\n- [x] done",
			want: []string{"☐ todo", "☑ done"},
		},
		{
			name: "nested blockquote",
			md:   "> outer\n>> inner",
			want: []string{"│ outer", "│ │ inner"},
		},
		{
			name: "blockquote with code fence",
			md:   "> text\n>\n> ```\n> code\n> ```",
			want: []string{"│ text", "│ │ code"},
		},
		{
			name:    "link with distinct text",
			md:      "see [Onyx docs](https://docs.onyx.app) here",
			want:    []string{"Onyx docs", "(https://docs.onyx.app)"},
			notWant: []string{"["},
		},
		{
			name: "autolink",
			md:   "go to <https://onyx.app> now",
			want: []string{"https://onyx.app"},
		},
		{
			name: "image",
			md:   "![a diagram](diagram.png)",
			want: []string{"[image: a diagram]"},
		},
		{
			name: "hard break",
			md:   "line one  \nline two",
			want: []string{"line one\nline two"},
		},
		{
			name: "thematic break",
			md:   "above\n\n---\n\nbelow",
			want: []string{"────"},
		},
		{
			name: "raw html passthrough",
			md:   "before <br> after",
			want: []string{"before <br> after"},
		},
		{
			name: "table",
			md:   "| Name | Count |\n|------|------:|\n| foo | 1 |\n| barbar | 22 |",
			want: []string{"Name", "│", "┼", "foo", "barbar", "22"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			out := stripANSI(render(t, tt.md, 80))
			for _, w := range tt.want {
				if !strings.Contains(out, w) {
					t.Errorf("expected output to contain %q, got:\n%s", w, out)
				}
			}
			for _, nw := range tt.notWant {
				if strings.Contains(out, nw) {
					t.Errorf("expected output to NOT contain %q, got:\n%s", nw, out)
				}
			}
		})
	}
}

// sgrParams returns the parameter lists of all SGR sequences in s.
func sgrParams(s string) [][]string {
	var out [][]string
	for _, m := range ansiRegex.FindAllString(s, -1) {
		params := strings.TrimSuffix(strings.TrimPrefix(m, "\x1b["), "m")
		out = append(out, strings.Split(params, ";"))
	}
	return out
}

func hasParams(seqs [][]string, want ...string) bool {
	for _, params := range seqs {
		found := 0
		for _, w := range want {
			for _, p := range params {
				if p == w {
					found++
					break
				}
			}
		}
		if found == len(want) {
			return true
		}
	}
	return false
}

func TestMergedEmphasisStyling(t *testing.T) {
	out := render(t, "**bold *and italic* rest**", 80)
	seqs := sgrParams(out)
	if !hasParams(seqs, "1") {
		t.Errorf("expected a bold SGR sequence, got %q", out)
	}
	// The nested leaf must carry BOTH bold and italic in a single merged
	// style, not italic layered over a reset bold.
	if !hasParams(seqs, "1", "3") {
		t.Errorf("expected a merged bold+italic SGR sequence, got %q", out)
	}
	// After the italic span closes, the trailing text must still be bold.
	idx := strings.LastIndex(out, "rest")
	if idx == -1 {
		t.Fatalf("missing trailing text in %q", out)
	}
	if !hasParams(sgrParams(out[:idx]), "1") {
		t.Errorf("expected bold to be re-opened for trailing text, got %q", out)
	}
}

func TestBodyTextColored(t *testing.T) {
	// Plain agent prose carries the body text color (ANSI 252) so responses
	// stay distinct from default-foreground UI text.
	out := render(t, "plain paragraph text", 80)
	if !hasParams(sgrParams(out), "38", "5", "252") {
		t.Errorf("expected body text foreground SGR, got %q", out)
	}
}

func TestTableTruncation(t *testing.T) {
	md := "| A | B |\n|---|---|\n| " + strings.Repeat("x", 100) + " | y |"
	out := stripANSI(render(t, md, 40))
	if !strings.Contains(out, "…") {
		t.Errorf("expected overflow cell to be ellipsis-truncated, got:\n%s", out)
	}
}

func TestWidthInvariant(t *testing.T) {
	inputs := map[string]string{
		"long token":    "start " + strings.Repeat("x", 500) + " end",
		"long url":      "see https://example.com/" + strings.Repeat("path/", 100) + " now",
		"long code":     "```\n" + strings.Repeat("verylongcodetoken", 40) + "\n```",
		"cjk paragraph": strings.Repeat("汉字宽度测试 ", 60),
		"emoji":         strings.Repeat("🎉 party ", 50),
		"wide table":    "| one | two | three | four |\n|---|---|---|---|\n| " + strings.Repeat("wide ", 30) + " | b | c | d |",
		"nested":        "> - item " + strings.Repeat("word ", 50) + "\n> - second",
		"deep nesting":  strings.Repeat("> ", 30) + "deeply quoted " + strings.Repeat("word ", 20),
		"kitchen sink":  kitchenSink,
	}
	// Narrow widths matter: the viewport passes terminal width minus its
	// indent, and rendering wider than asked makes the terminal soft-wrap,
	// desyncing the viewport's row accounting.
	for name, md := range inputs {
		for _, width := range []int{4, 12, 20, 40, 80} {
			out := NewRenderer(width).Render(md)
			for i, line := range strings.Split(out, "\n") {
				if w := ansi.StringWidthWc(stripANSI(line)); w > width {
					t.Errorf("%s @%d: line %d has width %d > %d: %q",
						name, width, i, w, width, stripANSI(line))
				}
			}
		}
	}
}

func TestStreamingPrefixesNoPanic(t *testing.T) {
	runes := []rune(kitchenSink)
	r := NewRenderer(60)
	for i := 0; i <= len(runes); i++ {
		_ = r.Render(string(runes[:i]))
	}
}

func TestRendererClampsWidth(t *testing.T) {
	out := NewRenderer(0).Render("hello world")
	if stripANSI(out) == "" {
		t.Error("expected non-empty output at clamped width")
	}
}

func TestEmptyAndWhitespaceInput(t *testing.T) {
	for _, md := range []string{"", "   ", "\n\n\n"} {
		if out := render(t, md, 80); strings.TrimSpace(stripANSI(out)) != "" {
			t.Errorf("expected empty render for %q, got %q", md, out)
		}
	}
}

const kitchenSink = `# Report

Intro paragraph with **bold**, *italic*, ` + "`code`" + `, a [link](https://onyx.app),
and ~~strikethrough~~.

## Details

1. first item
2. second item with a nested list:
   - alpha
   - beta

> A blockquote with ` + "`inline code`" + ` inside.

` + "```go" + `
func main() {
	fmt.Println("hello")
}
` + "```" + `

| Feature | Status |
|---------|--------|
| Search  | done   |
| Chat    | wip    |

---

Final paragraph with 汉字 and an emoji 🎉.
`
