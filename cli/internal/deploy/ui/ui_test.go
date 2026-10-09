package ui

import (
	"bytes"
	"strings"
	"testing"
	"time"

	"github.com/charmbracelet/x/ansi"

	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
)

// sampleModels covers the panes that carry the widest content: a question with
// long hints, and a running phase with a per-service checklist.
func sampleModels() map[string]wizModel {
	began := time.Now().Add(-42 * time.Second)
	return map[string]wizModel{
		"question": {
			title:   "Onyx Installer",
			version: "v0.1.0",
			stage:   StageConfigure,
			sel: &askSelectMsg{
				title: "How should Onyx be deployed?",
				opts: []Option{
					{Label: "Lite", Hint: "chat, tools, uploads, projects — no vector search (recommended)"},
					{Label: "Standard", Hint: "full search, connectors, and RAG"},
					{Label: "Standard + Craft", Hint: "adds AI web-app building (binds the docker socket)"},
				},
			},
			notes: []noteMsg{{"ok", "Deployment files are up to date"}},
		},
		// The star question is the one that carries an emoji: a glyph the
		// terminal draws two columns wide has to be measured as two.
		"confirm": {
			title:   "Onyx Installer",
			version: "v0.1.0",
			stage:   StageComplete,
			answers: []answerMsg{{"Mode", "Lite"}, {"Version", "v4.4.6"}},
			sel: &askSelectMsg{
				title: "Enjoying Onyx? ⭐ Star the repo on GitHub?",
				opts:  []Option{{Label: "Yes"}, {Label: "No"}},
			},
		},
		"task": {
			title:      "Onyx Installer",
			version:    "v0.1.0",
			stage:      StagePull,
			answers:    []answerMsg{{"Action", "Upgrade"}, {"Version", "v4.4.6"}},
			taskLabel:  "Pulling images",
			taskExtra:  "3/9 images · 1.2 GB / 4.8 GB",
			taskActive: true,
			taskBegan:  began,
			services: []ServiceRow{
				{Name: "backend", Ready: true},
				{Name: "web_server", Detail: "62%  310.4 MB / 500.1 MB"},
				{Name: "model_server", Detail: "4%  21.0 MB / 512.5 MB"},
				{Name: "relational_db", Detail: "waiting"},
			},
			notes: []noteMsg{{"", "Using deployment/.env from the existing install"}},
		},
	}
}

// The wizard has to fit the terminal it was given: anything wider wraps and
// smears the full-screen layout across lines.
func TestViewFitsTerminalWidth(t *testing.T) {
	sizes := []struct{ w, h int }{{40, 12}, {52, 16}, {64, 20}, {80, 24}, {120, 40}}
	for name, base := range sampleModels() {
		for _, size := range sizes {
			m := base
			m.width, m.height = size.w, size.h
			lines := strings.Split(m.View().Content, "\n")
			for i, line := range lines {
				if got := ansi.StringWidthWc(line); got > size.w {
					t.Errorf("%s at %dx%d: line %d is %d columns wide:\n%s",
						name, size.w, size.h, i+1, got, line)
				}
			}
			if len(lines) > size.h {
				t.Errorf("%s at %dx%d: view is %d lines tall", name, size.w, size.h, len(lines))
			}
		}
	}
}

// The boxes are as wide as the terminal, whatever is in them: one that takes
// its width from its longest line makes the layout look like it shrinks
// whenever a phase has less to say.
func TestBoxesFillTerminalWidth(t *testing.T) {
	sizes := []int{64, 80, 100, 120}
	for name, base := range sampleModels() {
		for _, w := range sizes {
			m := base
			m.width, m.height = w, 30
			if got := borderWidth(m.View().Content); got != w {
				t.Errorf("%s at %d columns: pane border is %d wide", name, w, got)
			}
		}
	}

	// The summary card is printed to the normal screen after the wizard is
	// gone, and has to line up with what it just replaced.
	for _, w := range sizes {
		var buf bytes.Buffer
		wiz := &Wizard{out: &buf}
		wiz.printTail(wizModel{width: w, card: []string{
			"🎉 Onyx is ready  →  http://localhost:3000",
			"",
			"Manage this deployment any time with:",
			"  onyx-cli deploy status      health, version, and URL",
		}})
		if got := borderWidth(buf.String()); got != w {
			t.Errorf("summary card at %d columns: border is %d wide", w, got)
		}
	}
}

// An indented card line that outgrows the card continues under itself: the
// command list the card ends with would otherwise look like twice as many
// commands as it lists.
func TestNarrowCardHangsWrappedLines(t *testing.T) {
	var buf bytes.Buffer
	wiz := &Wizard{out: &buf}
	wiz.printTail(wizModel{width: 44, card: []string{
		"  onyx-cli deploy uninstall   remove it and its data",
	}})

	for _, line := range strings.Split(buf.String(), "\n") {
		plain := ansi.Strip(line)
		if !strings.Contains(plain, "its data") {
			continue
		}
		body := plain[strings.Index(plain, "│")+len("│"):]
		// Two columns of card padding, then the line's own indent.
		if !strings.HasPrefix(body, "    it and its data") {
			t.Errorf("wrapped line lost its indent:\n%s", buf.String())
		}
		return
	}
	t.Errorf("the line never wrapped:\n%s", buf.String())
}

// The last thing an install does is ask a question, and quitting it kills the
// wizard. The work is over by then, so the summary still has to be printed —
// there is nowhere else for the user to find the URL.
func TestFinishPrintsCardAfterQuit(t *testing.T) {
	var buf bytes.Buffer
	done := make(chan struct{})
	close(done)
	wiz := &Wizard{out: &buf, done: done, width: 80}

	wiz.Finish("🎉 Onyx is ready  →  http://localhost:3000")

	if !strings.Contains(buf.String(), "http://localhost:3000") {
		t.Errorf("the summary was dropped with the wizard:\n%s", buf.String())
	}
	if got := borderWidth(buf.String()); got != 80 {
		t.Errorf("card border is %d wide, want 80", got)
	}
}

// borderWidth is the display width of the first box-drawing line in content,
// or 0 when there is none.
func borderWidth(content string) int {
	for _, line := range strings.Split(content, "\n") {
		if strings.Contains(line, "╭") {
			return ansi.StringWidthWc(line)
		}
	}
	return 0
}

// A download note that no longer fits sheds whole parts: cutting it mid-figure
// would leave a unit-less number on screen.
func TestNarrowChecklistKeepsPercent(t *testing.T) {
	m := sampleModels()["task"]
	m.width, m.height = 64, 24
	content := m.View().Content
	if !strings.Contains(content, "62%") {
		t.Errorf("the percentage should outlive the byte figures:\n%s", content)
	}
	if strings.Contains(content, "310.4") {
		t.Errorf("byte figures should be dropped whole, not clipped:\n%s", content)
	}
}

// Hints read as a column, not as text stepping in and out with the labels —
// except where the column would cost a hint its place beside its option.
func TestOptionHintsShareAColumn(t *testing.T) {
	opts := []Option{
		{Label: "Lite", Hint: "chat, tools, uploads, projects — no vector search (recommended)"},
		{Label: "Standard", Hint: "full search, connectors, and RAG"},
		{Label: "Standard + Craft", Hint: "adds AI web-app building (binds the docker socket)"},
	}
	m := wizModel{sel: &askSelectMsg{title: "How should Onyx be deployed?", opts: opts}}

	// Roomy: every hint starts past the widest label, at the same column.
	want := cursorWidth + ansi.StringWidthWc("Standard + Craft") + hintGap
	for i, line := range m.selectPane(94, true, false)[1:] {
		got := hintStart(line, opts[i].Hint)
		if got != want {
			t.Errorf("hint %d starts at column %d, want %d:\n%s", i, got, want, line)
		}
	}

	// Tight: at 74 columns all three hints still fit beside their own label,
	// and lining them up would push the first onto a line of its own.
	pane := m.selectPane(74, true, false)
	if len(pane) != 1+len(opts) {
		t.Errorf("the column cost a hint its place beside its option:\n%s", strings.Join(pane, "\n"))
	}
	if got := hintStart(pane[1], opts[0].Hint); got != cursorWidth+ansi.StringWidthWc("Lite")+hintGap {
		t.Errorf("hint 0 should follow its own label at 74 columns, starts at %d", got)
	}
}

// hintStart is the column hint begins at within a rendered option line.
func hintStart(line, hint string) int {
	plain := ansi.Strip(line)
	i := strings.Index(plain, hint)
	if i < 0 {
		return -1
	}
	return ansi.StringWidthWc(plain[:i])
}

// Long option hints must survive a narrow screen, wrapped under their option
// rather than truncated away.
func TestNarrowViewKeepsOptionHints(t *testing.T) {
	m := sampleModels()["question"]
	m.width, m.height = 44, 20
	content := m.View().Content
	if !strings.Contains(content, "vector search") {
		t.Errorf("hint text was dropped at 44 columns:\n%s", content)
	}
	if !strings.Contains(content, "Step 1/4") {
		t.Errorf("the rail should collapse to a step line below %d columns:\n%s", minTwoColumn, content)
	}
}

// A Painter colors only what the stream can show: styled on a terminal,
// untouched when the output is piped or the environment opts out.
func TestPainterFollowsTheStream(t *testing.T) {
	tty := &iostreams.IOStreams{Out: &bytes.Buffer{}, IsStdoutTTY: true}
	t.Setenv("TERM", "xterm-256color")
	t.Setenv("NO_COLOR", "")

	p := NewPainter(tty)
	for _, styled := range []string{p.Ok("up"), p.Warn("up"), p.Err("up"), p.Dim("up")} {
		if styled == "up" {
			t.Error("a terminal stream should be colored")
		}
		if ansi.Strip(styled) != "up" {
			t.Errorf("styling changed the text: %q", ansi.Strip(styled))
		}
	}
	if p.Ok("up") == p.Err("up") {
		t.Error("healthy and failed states must not look the same")
	}

	piped := NewPainter(&iostreams.IOStreams{Out: &bytes.Buffer{}})
	if got := piped.Err("up"); got != "up" {
		t.Errorf("piped output should stay plain, got %q", got)
	}
	t.Setenv("NO_COLOR", "1")
	if got := NewPainter(tty).Err("up"); got != "up" {
		t.Errorf("NO_COLOR should stay plain, got %q", got)
	}
}

// The accent and the secondary grey follow the terminal's background: the
// same text is styled differently on a light terminal than on a dark one,
// and a stream that can't be asked keeps the dark default rather than
// guessing.
func TestColorsFollowTheBackground(t *testing.T) {
	t.Cleanup(func() { useBackground(true) })
	t.Setenv("TERM", "xterm-256color")
	t.Setenv("NO_COLOR", "")
	tty := &iostreams.IOStreams{Out: &bytes.Buffer{}, IsStdinTTY: true, IsStdoutTTY: true}

	t.Setenv(BackgroundEnv, "light")
	if darkBackground(tty) {
		t.Error("an explicit light background should be honored")
	}
	t.Setenv(BackgroundEnv, "Dark")
	if !darkBackground(tty) {
		t.Error("an explicit dark background should be honored")
	}
	t.Setenv(BackgroundEnv, "")
	if !darkBackground(&iostreams.IOStreams{Out: &bytes.Buffer{}}) {
		t.Error("a stream that can't be queried should stay on the dark default")
	}

	const text = "onyx-cli deploy status"
	useBackground(true)
	darkAccent, darkDim := Accent(text), dim.Render(text)
	useBackground(false)
	lightAccent, lightDim := Accent(text), dim.Render(text)

	for _, c := range []struct{ what, dark, light string }{
		{"accent", darkAccent, lightAccent},
		{"dim", darkDim, lightDim},
	} {
		if c.dark == c.light {
			t.Errorf("%s should differ between light and dark backgrounds", c.what)
		}
		if ansi.Strip(c.light) != text {
			t.Errorf("%s styling changed the text: %q", c.what, ansi.Strip(c.light))
		}
	}
}
