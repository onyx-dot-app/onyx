// Package ui renders the interactive installer as a single live wizard: a
// persistent Bubble Tea program with a step rail, an active pane for
// questions and progress, and a final summary card. The deploy orchestration
// falls back to plain line output when a real TTY isn't driving the run, so
// CI logs and --no-prompt behavior stay stable.
package ui

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

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

// ServiceRow is one container's live state during startup.
type ServiceRow struct {
	Name  string
	Ready bool
}

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
	version string
	stage   int
	answers []answerMsg
	notes   []noteMsg

	sel    *askSelectMsg
	cursor int
	inp    *askInputMsg
	typed  string

	taskLabel, taskExtra string
	taskActive           bool
	taskBegan            time.Time
	frame                int
	services             []ServiceRow

	card    []string
	aborted bool
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
	case askSelectMsg:
		m.sel, m.cursor = &msg, msg.def
		return m, nil
	case askInputMsg:
		m.inp, m.typed = &msg, ""
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
			m.aborted = true
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
			m.aborted = true
			return m, tea.Quit
		case "backspace":
			if len(m.typed) > 0 {
				m.typed = m.typed[:len(m.typed)-1]
			}
		default:
			if len([]rune(s)) == 1 && !strings.Contains(s, "+") {
				m.typed += s
			}
		}
		return m, nil
	}
	if s == "ctrl+c" {
		m.aborted = true
		return m, tea.Quit
	}
	return m, nil
}

func (m wizModel) View() tea.View {
	if m.card != nil {
		return tea.NewView(cardBox.Render(strings.Join(m.card, "\n")) + "\n")
	}
	if m.aborted {
		return tea.NewView("")
	}

	// Left rail: stages + recorded answers.
	var rail []string
	for i, name := range stageNames {
		mark, style := "○", dim
		switch {
		case i < m.stage:
			mark, style = okStyle.Render("✓"), okStyle
		case i == m.stage:
			mark, style = accent.Render("●"), railOn
		}
		rail = append(rail, fmt.Sprintf(" %s %s", mark, style.Render(name)))
	}
	rail = append(rail, "")
	for _, a := range m.answers {
		rail = append(rail, dim.Render(fmt.Sprintf(" %-8s", a.label))+accent.Render(a.value))
	}

	// Active pane: question, live task, or quiet.
	var pane []string
	switch {
	case m.sel != nil:
		pane = append(pane, accent.Render("? ")+m.sel.title)
		for i, o := range m.sel.opts {
			cursor, label := "  ", o.Label
			if i == m.cursor {
				cursor, label = accent.Render("› "), accent.Render(o.Label)
			}
			line := cursor + label
			if o.Hint != "" {
				line += "  " + dim.Render(o.Hint)
			}
			pane = append(pane, line)
		}
	case m.inp != nil:
		shown := m.typed
		if shown == "" {
			shown = dim.Render(m.inp.def)
		}
		pane = append(pane, accent.Render("? ")+m.inp.title, "  "+shown+accent.Render("▏"))
	case m.taskActive:
		line := fmt.Sprintf("%s %s %s", accent.Render(spinners[m.frame%len(spinners)]),
			m.taskLabel, dim.Render(fmt.Sprintf("(%ds)", int(time.Since(m.taskBegan).Seconds()))))
		if m.taskExtra != "" {
			line += " " + dim.Render(m.taskExtra)
		}
		pane = append(pane, line)
		for _, svc := range m.services {
			mark := dim.Render(spinners[m.frame%len(spinners)])
			if svc.Ready {
				mark = okStyle.Render("✓")
			}
			pane = append(pane, fmt.Sprintf("  %s %s", mark, svc.Name))
		}
	default:
		pane = append(pane, dim.Render("…"))
	}

	body := lipgloss.JoinHorizontal(lipgloss.Top,
		lipgloss.NewStyle().Width(22).Render(strings.Join(rail, "\n")),
		paneBox.Render(strings.Join(pane, "\n")))

	var b strings.Builder
	fmt.Fprintf(&b, "%s %s\n\n", accent.Render("🚀 Onyx Installer"), dim.Render(m.version))
	b.WriteString(body + "\n")
	for _, n := range m.notes {
		switch n.level {
		case "ok":
			b.WriteString(okStyle.Render("✓ ") + n.text + "\n")
		case "warn":
			b.WriteString(warnSt.Render("⚠ ") + n.text + "\n")
		case "err":
			b.WriteString(errSt.Render("✗ ") + n.text + "\n")
		default:
			b.WriteString(dim.Render("  "+n.text) + "\n")
		}
	}
	b.WriteString(dim.Render("↑/↓ move · enter confirm · ctrl+c quit"))
	return tea.NewView(b.String())
}

// Wizard drives the model from the orchestration goroutine.
type Wizard struct {
	prog *tea.Program
	done chan struct{}
}

// StartWizard launches the inline wizard program.
func StartWizard(version string) *Wizard {
	w := &Wizard{
		prog: tea.NewProgram(wizModel{version: version}),
		done: make(chan struct{}),
	}
	go func() {
		_, _ = w.prog.Run()
		close(w.done)
	}()
	return w
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

// Finish renders the summary card as the final scrollback view and exits.
func (w *Wizard) Finish(lines ...string) {
	w.prog.Send(finishMsg(lines))
	w.prog.Wait()
}

// Abort tears the wizard down (no-op after Finish).
func (w *Wizard) Abort() {
	select {
	case <-w.done:
		return
	default:
	}
	w.prog.Send(abortMsg{})
	w.prog.Wait()
}

// Accent styles a string for emphasis outside the wizard (plain summaries).
func Accent(s string) string { return accent.Render(s) }
