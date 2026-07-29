// Package ui renders the interactive installer as a single live wizard: a
// full-screen (alt-screen) Bubble Tea program with a step rail, an active
// pane for questions and progress, and a final summary card. The alt screen
// is discarded when the program exits, so the wizard re-prints whatever the
// user still needs (the summary card, or the notes after an abort) to the
// normal screen where it survives in scrollback. The deploy orchestration
// falls back to plain line output when a real TTY isn't driving the run, so
// CI logs and --no-prompt behavior stay stable.
package ui

import (
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"

	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
)

var (
	accent   = lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Bold(true)
	dim      = lipgloss.NewStyle().Foreground(lipgloss.Color("8"))
	okStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("2"))
	warnSt   = lipgloss.NewStyle().Foreground(lipgloss.Color("3"))
	errSt    = lipgloss.NewStyle().Foreground(lipgloss.Color("1"))
	railOn   = lipgloss.NewStyle().Bold(true)
	cardBox  = lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(lipgloss.Color("6")).Padding(0, 2)
	paneBox  = lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(lipgloss.Color("8")).Padding(0, 1)
	spinners = []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"}
)

// Enabled reports whether the wizard should drive this run.
func Enabled(ios *iostreams.IOStreams) bool {
	return ios.IsInteractive() && os.Getenv("TERM") != "dumb" && os.Getenv("NO_COLOR") == ""
}

// ErrAborted is returned when the user cancels (ctrl+c / esc / q).
var ErrAborted = errors.New("cancelled")

// Option is one selectable choice.
type Option struct {
	Label string
	Hint  string
}

// ServiceRow is one item's live state in a phase checklist (an image being
// pulled, a container being started). Detail is the short right-aligned note
// after the name — a download total, or what is happening to the container.
type ServiceRow struct {
	Name   string
	Detail string
	Ready  bool
}

// Layout constants. The wizard is two columns when there is room for both;
// narrower screens drop the rail so the pane keeps the full width.
const (
	railWidth    = 22
	minTwoColumn = 64
	minPaneInner = 20
	// Sizes assumed until the first window-size message arrives.
	defaultWidth  = 80
	defaultHeight = 24
)

// Stages of the rail.
const (
	StageConfigure = iota
	StagePull
	StageStart
	StageDone
)

var stageNames = []string{"Configure", "Pull", "Start", "Done"}

type (
	askSelectMsg struct {
		title string
		opts  []Option
		def   int
		reply chan int // -1 = aborted
	}
	askInputMsg struct {
		title, def string
		reply      chan *string // nil = aborted
	}
	stageMsg     int
	answerMsg    struct{ label, value string }
	noteMsg      struct{ level, text string }
	taskStartMsg string
	taskExtraMsg string
	taskDoneMsg  struct{ ok bool }
	servicesMsg  []ServiceRow
	finishMsg    []string
	abortMsg     struct{}
	tickMsg      struct{}
)

type wizModel struct {
	title         string
	version       string
	stage         int
	answers       []answerMsg
	notes         []noteMsg
	width, height int

	sel    *askSelectMsg
	cursor int
	inp    *askInputMsg
	typed  string

	taskLabel, taskExtra string
	taskActive           bool
	taskBegan            time.Time
	frame                int
	services             []ServiceRow

	card     []string
	aborted  bool
	userQuit bool // aborted by a key press, not programmatically
}

func tick() tea.Cmd {
	return tea.Tick(120*time.Millisecond, func(time.Time) tea.Msg { return tickMsg{} })
}

func (m wizModel) Init() tea.Cmd { return tick() }

func (m wizModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tickMsg:
		m.frame++
		return m, tick()
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		return m, nil
	case askSelectMsg:
		m.sel, m.cursor = &msg, msg.def
		return m, nil
	case askInputMsg:
		// Prefill the default as real, editable text — backspacing to tweak
		// e.g. just the patch version beats retyping the whole tag.
		m.inp, m.typed = &msg, msg.def
		return m, nil
	case stageMsg:
		m.stage = int(msg)
		return m, nil
	case answerMsg:
		m.answers = append(m.answers, msg)
		return m, nil
	case noteMsg:
		m.notes = append(m.notes, msg)
		if len(m.notes) > 6 {
			m.notes = m.notes[len(m.notes)-6:]
		}
		return m, nil
	case taskStartMsg:
		m.taskLabel, m.taskExtra, m.taskActive, m.taskBegan = string(msg), "", true, time.Now()
		m.services = nil
		return m, nil
	case taskExtraMsg:
		m.taskExtra = string(msg)
		return m, nil
	case taskDoneMsg:
		m.taskActive = false
		level := "ok"
		if !msg.ok {
			level = "err"
		}
		m.notes = append(m.notes, noteMsg{level, fmt.Sprintf("%s (%ds)", m.taskLabel, int(time.Since(m.taskBegan).Seconds()))})
		return m, nil
	case servicesMsg:
		m.services = msg
		return m, nil
	case finishMsg:
		m.card = msg
		return m, tea.Quit
	case abortMsg:
		m.aborted = true
		return m, tea.Quit
	case tea.KeyPressMsg:
		return m.handleKey(msg)
	}
	return m, nil
}

func (m wizModel) handleKey(key tea.KeyPressMsg) (tea.Model, tea.Cmd) {
	s := key.String()
	if m.sel != nil {
		switch s {
		case "up", "k":
			if m.cursor > 0 {
				m.cursor--
			}
		case "down", "j", "tab":
			if m.cursor < len(m.sel.opts)-1 {
				m.cursor++
			}
		case "1", "2", "3", "4":
			if idx := int(s[0] - '1'); idx < len(m.sel.opts) {
				m.cursor = idx
				m.sel.reply <- m.cursor
				m.sel = nil
			}
		case "enter":
			m.sel.reply <- m.cursor
			m.sel = nil
		case "ctrl+c", "esc", "q":
			m.sel.reply <- -1
			m.sel = nil
			m.aborted, m.userQuit = true, true
			return m, tea.Quit
		}
		return m, nil
	}
	if m.inp != nil {
		switch s {
		case "enter":
			v := strings.TrimSpace(m.typed)
			if v == "" {
				v = m.inp.def
			}
			m.inp.reply <- &v
			m.inp = nil
		case "ctrl+c", "esc":
			m.inp.reply <- nil
			m.inp = nil
			m.aborted, m.userQuit = true, true
			return m, tea.Quit
		case "backspace":
			// Rune-wise: byte slicing would split a multi-byte character.
			if r := []rune(m.typed); len(r) > 0 {
				m.typed = string(r[:len(r)-1])
			}
		case "ctrl+u":
			m.typed = ""
		default:
			if len([]rune(s)) == 1 && !strings.Contains(s, "+") {
				m.typed += s
			}
		}
		return m, nil
	}
	if s == "ctrl+c" {
		m.aborted, m.userQuit = true, true
		return m, tea.Quit
	}
	return m, nil
}

// renderNote styles one note line (shared by the live view and the
// post-exit tail).
func renderNote(n noteMsg, live bool) string {
	switch n.level {
	case "ok":
		return okStyle.Render("✓ ") + n.text
	case "warn":
		return warnSt.Render("⚠ ") + n.text
	case "err":
		return errSt.Render("✗ ") + n.text
	default:
		if live {
			return dim.Render("  " + n.text)
		}
		return "  " + n.text
	}
}

func (m wizModel) View() tea.View {
	width, height := m.width, m.height
	if width <= 0 {
		width = defaultWidth
	}
	if height <= 0 {
		height = defaultHeight
	}
	twoColumn := width >= minTwoColumn

	// Pane content width: the box adds a border and a column of padding on
	// each side, and the rail (when shown) takes the left of the screen.
	inner := width - 4
	if twoColumn {
		inner -= railWidth
	}
	inner = max(inner, minPaneInner)

	head := []string{"", " " + truncate(accent.Render("🚀 "+m.title)+" "+dim.Render(m.version), width-1), ""}
	help := " ↑/↓ move · enter confirm · ctrl+c quit"
	if !twoColumn {
		help = " ↑/↓ · enter · ctrl+c"
	}
	foot := []string{"", dim.Render(help)}
	var rail []string
	if !twoColumn {
		rail = m.compactRail(width - 1)
	}
	notes := make([]string, 0, len(m.notes))
	for _, n := range m.notes {
		notes = append(notes, truncate(renderNote(n, true), width-1))
	}

	// The pane is the only part that can shed content, so it is what gives on
	// a short screen: everything else here is fixed height (the box adds a
	// border row above and below).
	budget := height - len(head) - len(rail) - len(notes) - len(foot) - 2
	pane := paneBox.Render(strings.Join(m.paneLines(inner, max(budget, 3)), "\n"))

	lines := make([]string, 0, height)
	lines = append(lines, head...)
	if twoColumn {
		lines = append(lines, strings.Split(lipgloss.JoinHorizontal(lipgloss.Top,
			lipgloss.NewStyle().Width(railWidth).Render(strings.Join(m.railLines(railWidth-1), "\n")),
			pane), "\n")...)
	} else {
		lines = append(lines, rail...)
		lines = append(lines, strings.Split(pane, "\n")...)
	}

	// Notes are re-printed on the normal screen when the wizard exits, so a
	// screen with no room for them loses the least by dropping the oldest.
	for len(notes) > 0 && len(lines)+len(notes)+len(foot) > height {
		notes = notes[1:]
	}
	lines = append(append(lines, notes...), foot...)
	if len(lines) > height {
		lines = lines[:height]
	}

	v := tea.NewView(strings.Join(lines, "\n"))
	v.AltScreen = true
	v.WindowTitle = m.title
	return v
}

// railLines renders the left rail: stages, then the answers recorded so far.
func (m wizModel) railLines(width int) []string {
	var rail []string
	for i, name := range stageNames {
		mark, style := "○", dim
		switch {
		case i < m.stage:
			mark, style = okStyle.Render("✓"), okStyle
		case i == m.stage:
			mark, style = accent.Render("●"), railOn
		}
		rail = append(rail, truncate(fmt.Sprintf(" %s %s", mark, style.Render(name)), width))
	}
	rail = append(rail, "")
	for _, a := range m.answers {
		rail = append(rail, truncate(dim.Render(fmt.Sprintf(" %-8s", a.label))+accent.Render(a.value), width))
	}
	return rail
}

// compactRail is the narrow-screen stand-in for the rail: the current step and
// the answers on one line each, above the pane instead of beside it.
func (m wizModel) compactRail(width int) []string {
	step := dim.Render(fmt.Sprintf("Step %d/%d", min(m.stage+1, len(stageNames)), len(stageNames)))
	lines := []string{truncate(" "+step+" "+railOn.Render(stageNames[min(m.stage, len(stageNames)-1)]), width)}
	if len(m.answers) > 0 {
		parts := make([]string, 0, len(m.answers))
		for _, a := range m.answers {
			parts = append(parts, dim.Render(a.label+" ")+accent.Render(a.value))
		}
		lines = append(lines, truncate(" "+strings.Join(parts, dim.Render(" · ")), width))
	}
	return lines
}

// paneLines renders the active pane — a question, the live task, or nothing —
// within inner columns and at most maxLines rows, dropping the optional parts
// (hints, checklist rows) rather than running off a short screen.
func (m wizModel) paneLines(inner, maxLines int) []string {
	switch {
	case m.sel != nil:
		// Shed the optional parts before the options themselves: a question
		// the user can't see the choices for is worse than a terse one.
		pane := m.selectPane(inner, true, true)
		if len(pane) > maxLines {
			pane = m.selectPane(inner, false, true)
		}
		if len(pane) > maxLines {
			pane = m.selectPane(inner, false, false)
		}
		return clip(pane, maxLines)
	case m.inp != nil:
		return clip(append(wrap(accent.Render("? ")+m.inp.title, inner),
			truncate("  "+m.typed+accent.Render("▏"), inner)), maxLines)
	case m.taskActive:
		return clip(m.taskPane(inner, maxLines), maxLines)
	default:
		return []string{dim.Render("…")}
	}
}

// selectPane renders the question and its options. hints and a wrapped (as
// opposed to single-line) title are what it gives up, in that order, when the
// pane has to get shorter.
func (m wizModel) selectPane(inner int, hints, wrapTitle bool) []string {
	title := accent.Render("? ") + m.sel.title
	pane := []string{truncate(title, inner)}
	if wrapTitle {
		pane = wrap(title, inner)
	}
	for i, o := range m.sel.opts {
		cursor, label := "  ", o.Label
		if i == m.cursor {
			cursor, label = accent.Render("› "), accent.Render(o.Label)
		}
		line := cursor + label
		if o.Hint == "" || !hints {
			pane = append(pane, truncate(line, inner))
			continue
		}
		// Keep the hint beside its option while it fits; otherwise it wraps
		// underneath rather than being cut off.
		if lipgloss.Width(line)+2+lipgloss.Width(o.Hint) <= inner {
			pane = append(pane, line+"  "+dim.Render(o.Hint))
			continue
		}
		pane = append(pane, truncate(line, inner))
		for _, h := range wrap(o.Hint, inner-4) {
			pane = append(pane, "    "+dim.Render(h))
		}
	}
	return pane
}

// clip keeps a pane within its row budget, marking what it cut.
func clip(lines []string, maxLines int) []string {
	if maxLines < 1 || len(lines) <= maxLines {
		return lines
	}
	return append(lines[:maxLines-1:maxLines-1], dim.Render("  …"))
}

// taskPane renders the running task and its checklist, within maxLines rows.
func (m wizModel) taskPane(inner, maxLines int) []string {
	spin := spinners[m.frame%len(spinners)]
	head := fmt.Sprintf("%s %s %s", accent.Render(spin), m.taskLabel,
		dim.Render(fmt.Sprintf("(%ds)", int(time.Since(m.taskBegan).Seconds()))))
	var pane []string
	switch {
	case m.taskExtra == "":
		pane = []string{truncate(head, inner)}
	case lipgloss.Width(head)+1+lipgloss.Width(m.taskExtra) <= inner:
		pane = []string{head + " " + dim.Render(m.taskExtra)}
	default:
		pane = []string{truncate(head, inner), truncate("  "+dim.Render(m.taskExtra), inner)}
	}

	rows := m.services
	// One row is held back for the "… n more" line whenever some are cut.
	if room := maxLines - len(pane); len(rows) > room {
		rows = rows[:max(room-1, 0)]
	}
	for _, svc := range rows {
		mark := dim.Render(spin)
		if svc.Ready {
			mark = okStyle.Render("✓")
		}
		line := fmt.Sprintf("  %s %s", mark, svc.Name)
		if detail := fitDetail(svc.Detail, inner-lipgloss.Width(line)-1); detail != "" {
			// Right-aligned so the figures form a column instead of jittering
			// with every name length.
			gap := max(inner-lipgloss.Width(line)-lipgloss.Width(detail), 1)
			line += strings.Repeat(" ", gap) + dim.Render(detail)
		}
		pane = append(pane, truncate(line, inner))
	}
	if hidden := len(m.services) - len(rows); hidden > 0 {
		pane = append(pane, dim.Render(fmt.Sprintf("  … %d more", hidden)))
	}
	return pane
}

// fitDetail shortens a checklist note to the room left on its row. Notes are
// written most-significant-part first and separated by a double space
// ("62%" then "310.4 MB / 500.1 MB"), so shedding trailing parts keeps the
// figure worth reading; a note that still doesn't fit is dropped rather than
// truncated into a unit-less number.
func fitDetail(detail string, room int) string {
	if detail == "" || room < 1 {
		return ""
	}
	if lipgloss.Width(detail) <= room {
		return detail
	}
	parts := strings.Split(detail, "  ")
	for len(parts) > 1 {
		parts = parts[:len(parts)-1]
		if s := strings.TrimSpace(strings.Join(parts, "  ")); lipgloss.Width(s) <= room {
			return s
		}
	}
	return ""
}

// truncate/wrap are the width guards for every line the wizard prints; both
// are ANSI-aware, and both refuse widths x/ansi would treat as "no limit".
func truncate(s string, width int) string {
	if width < 1 {
		return ""
	}
	return ansi.TruncateWc(s, width, "…")
}

func wrap(s string, width int) []string {
	if width < 1 {
		return []string{}
	}
	return strings.Split(ansi.WrapWc(s, width, " -/"), "\n")
}

// Wizard drives the model from the orchestration goroutine.
type Wizard struct {
	prog *tea.Program
	done chan struct{}
	out  io.Writer
}

// StartWizard launches the full-screen wizard program. onAbort fires only
// when the user quits the wizard (ctrl+c/esc) so the orchestration can
// cancel any in-flight work — without it, killing the UI would leave
// compose running. A programmatic Abort (teardown before plain output) must
// NOT fire it, or real failures get misreported as cancellations.
func StartWizard(out io.Writer, title, version string, onAbort func()) *Wizard {
	w := &Wizard{
		prog: tea.NewProgram(wizModel{title: title, version: version}),
		done: make(chan struct{}),
		out:  out,
	}
	go func() {
		m, _ := w.prog.Run()
		wm, ok := m.(wizModel)
		if ok {
			w.printTail(wm)
		}
		close(w.done)
		if ok && wm.userQuit && onAbort != nil {
			onAbort()
		}
	}()
	return w
}

// printTail re-prints what the discarded alt screen was showing to the
// normal screen, where it survives in scrollback: the summary card when the
// run finished, otherwise the accumulated notes — exactly what the user
// needs after an abort or failure.
func (w *Wizard) printTail(m wizModel) {
	width := m.width
	if width <= 0 {
		width = defaultWidth
	}
	if m.card != nil {
		var lines []string
		for _, l := range m.card {
			lines = append(lines, wrap(l, max(width-6, minPaneInner))...)
		}
		fmt.Fprintln(w.out, cardBox.Render(strings.Join(lines, "\n")))
		return
	}
	for _, n := range m.notes {
		fmt.Fprintln(w.out, truncate(renderNote(n, false), width))
	}
}

// Select asks an arrow-key question and blocks for the answer.
func (w *Wizard) Select(title string, opts []Option, def int) (int, error) {
	reply := make(chan int, 1)
	w.prog.Send(askSelectMsg{title: title, opts: opts, def: def, reply: reply})
	select {
	case v := <-reply:
		if v < 0 {
			return 0, ErrAborted
		}
		return v, nil
	case <-w.done:
		return 0, ErrAborted
	}
}

// Input asks a free-form value with a prefilled default.
func (w *Wizard) Input(title, def string) (string, error) {
	reply := make(chan *string, 1)
	w.prog.Send(askInputMsg{title: title, def: def, reply: reply})
	select {
	case v := <-reply:
		if v == nil {
			return "", ErrAborted
		}
		return *v, nil
	case <-w.done:
		return "", ErrAborted
	}
}

// Stage advances the rail; Answer records a decision beneath it.
func (w *Wizard) Stage(s int)             { w.prog.Send(stageMsg(s)) }
func (w *Wizard) Answer(label, v string)  { w.prog.Send(answerMsg{label, v}) }
func (w *Wizard) Note(level, text string) { w.prog.Send(noteMsg{level, text}) }

// TaskStart/TaskExtra/TaskDone drive the pane's live task line.
func (w *Wizard) TaskStart(label string)     { w.prog.Send(taskStartMsg(label)) }
func (w *Wizard) TaskExtra(extra string)     { w.prog.Send(taskExtraMsg(extra)) }
func (w *Wizard) TaskDone(ok bool)           { w.prog.Send(taskDoneMsg{ok}) }
func (w *Wizard) Services(rows []ServiceRow) { w.prog.Send(servicesMsg(rows)) }

// Suspend hands the terminal to fn (sudo prompts, provisioning output).
func (w *Wizard) Suspend(fn func() error) error {
	if err := w.prog.ReleaseTerminal(); err != nil {
		return fn()
	}
	defer func() { _ = w.prog.RestoreTerminal() }()
	return fn()
}

// Finish exits the wizard and prints the summary card to the normal screen.
// It blocks until the card has been written, so callers can keep printing
// plain output right after.
func (w *Wizard) Finish(lines ...string) {
	w.prog.Send(finishMsg(lines))
	<-w.done
}

// Abort tears the wizard down (no-op after Finish), leaving the accumulated
// notes on the normal screen. It blocks until they have been written.
func (w *Wizard) Abort() {
	select {
	case <-w.done:
		return
	default:
	}
	w.prog.Send(abortMsg{})
	<-w.done
}

// Accent styles a string for emphasis outside the wizard (plain summaries).
func Accent(s string) string { return accent.Render(s) }
