// Package ui renders the interactive installer experience: inline
// arrow-key prompts (Bubble Tea) and live spinner progress (lipgloss). The
// deploy orchestration falls back to plain line output when a real TTY isn't
// driving the run, so CI logs and --no-prompt behavior stay stable.
package ui

import (
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
)

var (
	accent  = lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Bold(true)
	dim     = lipgloss.NewStyle().Foreground(lipgloss.Color("8"))
	okMark  = lipgloss.NewStyle().Foreground(lipgloss.Color("2")).SetString("✓").String()
	errMark = lipgloss.NewStyle().Foreground(lipgloss.Color("1")).SetString("✗").String()
	boxLine = lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).Padding(0, 2)
)

// Enabled reports whether the fancy renderer should drive this run.
func Enabled(ios *iostreams.IOStreams) bool {
	return ios.IsInteractive() && os.Getenv("TERM") != "dumb" && os.Getenv("NO_COLOR") == ""
}

// ErrAborted is returned when the user cancels a prompt (ctrl+c / esc / q).
var ErrAborted = errors.New("cancelled")

// Option is one selectable choice.
type Option struct {
	Label string
	Hint  string
}

type selectModel struct {
	title   string
	options []Option
	cursor  int
	done    bool
	abort   bool
}

func (m selectModel) Init() tea.Cmd { return nil }

func (m selectModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if key, ok := msg.(tea.KeyPressMsg); ok {
		switch key.String() {
		case "up", "k":
			if m.cursor > 0 {
				m.cursor--
			}
		case "down", "j", "tab":
			if m.cursor < len(m.options)-1 {
				m.cursor++
			}
		case "1", "2", "3", "4":
			if idx := int(key.String()[0] - '1'); idx < len(m.options) {
				m.cursor = idx
			}
			m.done = true
			return m, tea.Quit
		case "enter":
			m.done = true
			return m, tea.Quit
		case "ctrl+c", "esc", "q":
			m.abort = true
			return m, tea.Quit
		}
	}
	return m, nil
}

func (m selectModel) View() tea.View {
	if m.done || m.abort {
		return tea.NewView("")
	}
	var b strings.Builder
	fmt.Fprintf(&b, "%s %s\n", accent.Render("?"), m.title)
	for i, o := range m.options {
		cursor, label := " ", o.Label
		if i == m.cursor {
			cursor, label = accent.Render("›"), accent.Render(o.Label)
		}
		hint := ""
		if o.Hint != "" {
			hint = "  " + dim.Render(o.Hint)
		}
		fmt.Fprintf(&b, "  %s %s%s\n", cursor, label, hint)
	}
	b.WriteString(dim.Render("  ↑/↓ to move · enter to confirm"))
	return tea.NewView(b.String())
}

// Select runs an inline arrow-key select and echoes the answer.
func Select(ios *iostreams.IOStreams, title string, options []Option, defaultIdx int) (int, error) {
	m := selectModel{title: title, options: options, cursor: defaultIdx}
	out, err := tea.NewProgram(m).Run()
	if err != nil {
		return 0, err
	}
	final := out.(selectModel)
	if final.abort {
		return 0, ErrAborted
	}
	fmt.Fprintf(ios.Out, "%s %s %s\n", okMark, title, accent.Render(options[final.cursor].Label))
	return final.cursor, nil
}

type inputModel struct {
	title      string
	defaultVal string
	value      string
	done       bool
	abort      bool
}

func (m inputModel) Init() tea.Cmd { return nil }

func (m inputModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if key, ok := msg.(tea.KeyPressMsg); ok {
		s := key.String()
		switch s {
		case "enter":
			m.done = true
			return m, tea.Quit
		case "ctrl+c", "esc":
			m.abort = true
			return m, tea.Quit
		case "backspace":
			if len(m.value) > 0 {
				m.value = m.value[:len(m.value)-1]
			}
		default:
			if len(s) == 1 || (len(s) > 0 && !strings.Contains(s, "+") && len([]rune(s)) == 1) {
				m.value += s
			}
		}
	}
	return m, nil
}

func (m inputModel) View() tea.View {
	if m.done || m.abort {
		return tea.NewView("")
	}
	shown := m.value
	if shown == "" {
		shown = dim.Render(m.defaultVal)
	}
	return tea.NewView(fmt.Sprintf("%s %s %s%s\n%s",
		accent.Render("?"), m.title, shown, accent.Render("▏"),
		dim.Render("  enter to accept")))
}

// Input runs an inline text prompt; empty submission returns defaultVal.
func Input(ios *iostreams.IOStreams, title, defaultVal string) (string, error) {
	m := inputModel{title: title, defaultVal: defaultVal}
	out, err := tea.NewProgram(m).Run()
	if err != nil {
		return "", err
	}
	final := out.(inputModel)
	if final.abort {
		return "", ErrAborted
	}
	value := strings.TrimSpace(final.value)
	if value == "" {
		value = defaultVal
	}
	fmt.Fprintf(ios.Out, "%s %s %s\n", okMark, title, accent.Render(value))
	return value, nil
}

// Task is a single-line live spinner: "⠋ label (12s) extra".
type Task struct {
	w     io.Writer
	label string

	mu    sync.Mutex
	extra string
	stop  chan struct{}
	wg    sync.WaitGroup
	start time.Time
}

var spinnerFrames = []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"}

// StartTask begins rendering a spinner line until Done is called.
func StartTask(w io.Writer, label string) *Task {
	t := &Task{w: w, label: label, stop: make(chan struct{}), start: time.Now()}
	t.wg.Add(1)
	go func() {
		defer t.wg.Done()
		frame := 0
		ticker := time.NewTicker(120 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-t.stop:
				return
			case <-ticker.C:
				t.mu.Lock()
				extra := t.extra
				t.mu.Unlock()
				if extra != "" {
					extra = " " + dim.Render(extra)
				}
				elapsed := dim.Render(fmt.Sprintf("(%ds)", int(time.Since(t.start).Seconds())))
				fmt.Fprintf(t.w, "\r\033[K%s %s %s%s",
					accent.Render(spinnerFrames[frame%len(spinnerFrames)]), t.label, elapsed, extra)
				frame++
			}
		}
	}()
	return t
}

// Update swaps the trailing status text.
func (t *Task) Update(extra string) {
	t.mu.Lock()
	t.extra = extra
	t.mu.Unlock()
}

// Done stops the spinner and prints the final ✓/✗ line.
func (t *Task) Done(ok bool, finalLabel string) {
	close(t.stop)
	t.wg.Wait()
	mark := okMark
	if !ok {
		mark = errMark
	}
	if finalLabel == "" {
		finalLabel = t.label
	}
	fmt.Fprintf(t.w, "\r\033[K%s %s %s\n", mark, finalLabel,
		dim.Render(fmt.Sprintf("(%ds)", int(time.Since(t.start).Seconds()))))
}

// Card renders the end-of-install summary box.
func Card(w io.Writer, lines ...string) {
	fmt.Fprintln(w, boxLine.Render(strings.Join(lines, "\n")))
}

// AccentURL styles a URL for the summary card.
func AccentURL(s string) string { return accent.Render(s) }
