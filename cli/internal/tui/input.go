package tui

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
)

// slashCommand defines a slash command with its description.
type slashCommand struct {
	command     string
	description string
}

var slashCommands = []slashCommand{
	{"/help", "Show help message"},
	{"/new", "Start a new chat session"},
	{"/agent", "List and switch agents"},
	{"/attach", "Attach a file to next message"},
	{"/sessions", "Browse and resume previous sessions"},
	{"/clear", "Clear the chat display"},
	{"/configure", "Re-run connection setup"},
	{"/connectors", "Open connectors in browser"},
	{"/settings", "Open settings in browser"},
	{"/quit", "Exit Onyx CLI"},
}

// Commands that take arguments (filled in with trailing space on Tab/Enter).
var argCommands = map[string]bool{
	"/attach": true,
}

// inputModel manages the text input and slash command menu.
type inputModel struct {
	textInput    textinput.Model
	menuVisible  bool
	menuItems    []slashCommand
	menuIndex    int
	attachedFiles []string
}

func newInputModel() inputModel {
	ti := textinput.New()
	ti.Prompt = "" // We render our own prompt in viewInput()
	ti.Placeholder = "Send a message…"
	ti.CharLimit = 10000
	// Don't focus here — focus after first WindowSizeMsg to avoid
	// capturing terminal init escape sequences as input.

	return inputModel{
		textInput: ti,
	}
}

func (m inputModel) update(msg tea.Msg) (inputModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		return m.handleKey(msg)
	}

	var cmd tea.Cmd
	m.textInput, cmd = m.textInput.Update(msg)
	m = m.updateMenu()
	return m, cmd
}

func (m inputModel) handleKey(msg tea.KeyMsg) (inputModel, tea.Cmd) {
	switch msg.Type {
	case tea.KeyUp:
		if m.menuVisible && m.menuIndex > 0 {
			m.menuIndex--
			return m, nil
		}
	case tea.KeyDown:
		if m.menuVisible && m.menuIndex < len(m.menuItems)-1 {
			m.menuIndex++
			return m, nil
		}
	case tea.KeyTab:
		if m.menuVisible && len(m.menuItems) > 0 {
			cmd := m.menuItems[m.menuIndex].command
			if argCommands[cmd] {
				m.textInput.SetValue(cmd + " ")
				m.textInput.SetCursor(len(cmd) + 1)
			} else {
				m.textInput.SetValue(cmd)
				m.textInput.SetCursor(len(cmd))
			}
			m.menuVisible = false
			return m, nil
		}
	case tea.KeyEnter:
		if m.menuVisible && len(m.menuItems) > 0 {
			cmd := m.menuItems[m.menuIndex].command
			if argCommands[cmd] {
				m.textInput.SetValue(cmd + " ")
				m.textInput.SetCursor(len(cmd) + 1)
				m.menuVisible = false
				return m, nil
			}
			// Execute immediately
			m.textInput.SetValue("")
			m.menuVisible = false
			return m, func() tea.Msg { return submitMsg{text: cmd} }
		}

		text := strings.TrimSpace(m.textInput.Value())
		if text == "" {
			return m, nil
		}

		// Check for file path (drag-and-drop)
		if dropped := detectFileDrop(text); dropped != "" {
			m.textInput.SetValue("")
			return m, func() tea.Msg { return fileDropMsg{path: dropped} }
		}

		m.textInput.SetValue("")
		m.menuVisible = false
		return m, func() tea.Msg { return submitMsg{text: text} }

	case tea.KeyEscape:
		if m.menuVisible {
			m.menuVisible = false
			return m, nil
		}
	}

	var cmd tea.Cmd
	m.textInput, cmd = m.textInput.Update(msg)
	m = m.updateMenu()
	return m, cmd
}

func (m inputModel) updateMenu() inputModel {
	val := strings.TrimSpace(m.textInput.Value())
	if strings.HasPrefix(val, "/") && !strings.Contains(val, " ") {
		needle := strings.ToLower(val)
		var filtered []slashCommand
		for _, sc := range slashCommands {
			if strings.HasPrefix(sc.command, needle) {
				filtered = append(filtered, sc)
			}
		}
		if len(filtered) > 0 {
			m.menuVisible = true
			m.menuItems = filtered
			if m.menuIndex >= len(filtered) {
				m.menuIndex = 0
			}
		} else {
			m.menuVisible = false
		}
	} else {
		m.menuVisible = false
	}
	return m
}

func (m *inputModel) addFile(name string) {
	m.attachedFiles = append(m.attachedFiles, name)
}

func (m *inputModel) clearFiles() {
	m.attachedFiles = nil
}

// submitMsg is sent when user submits text.
type submitMsg struct {
	text string
}

// fileDropMsg is sent when a file path is detected.
type fileDropMsg struct {
	path string
}

// detectFileDrop checks if the text looks like a file path.
func detectFileDrop(text string) string {
	cleaned := strings.Trim(text, "'\"")
	if cleaned == "" {
		return ""
	}
	// Expand ~ to home dir
	if strings.HasPrefix(cleaned, "~") {
		home, err := os.UserHomeDir()
		if err == nil {
			cleaned = filepath.Join(home, cleaned[1:])
		}
	}
	abs, err := filepath.Abs(cleaned)
	if err != nil {
		return ""
	}
	info, err := os.Stat(abs)
	if err != nil {
		return ""
	}
	if info.IsDir() {
		return ""
	}
	return abs
}

// viewMenu renders the slash command menu.
func (m inputModel) viewMenu(width int) string {
	if !m.menuVisible || len(m.menuItems) == 0 {
		return ""
	}

	var lines []string
	for i, item := range m.menuItems {
		prefix := "  "
		if i == m.menuIndex {
			prefix = "> "
		}
		line := prefix + item.command + "  " + statusMsgStyle.Render(item.description)
		lines = append(lines, line)
	}
	return strings.Join(lines, "\n")
}

// viewInput renders the input line with prompt and optional file badges.
func (m inputModel) viewInput() string {
	var parts []string

	if len(m.attachedFiles) > 0 {
		badges := strings.Join(m.attachedFiles, "] [")
		parts = append(parts, statusMsgStyle.Render("Attached: ["+badges+"]"))
	}

	parts = append(parts, inputPrompt+m.textInput.View())
	return strings.Join(parts, "\n")
}
