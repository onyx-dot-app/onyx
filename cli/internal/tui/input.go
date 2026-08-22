package tui

import (
	"os"
	"path/filepath"
	"strings"

	"charm.land/bubbles/v2/textinput"
	tea "charm.land/bubbletea/v2"
)

// slashCommand defines a slash command with its description.
type slashCommand struct {
	command     string
	description string
	// requiresArg commands are prefilled with a trailing space instead of
	// running when picked from the menu.
	requiresArg bool
	// optionalArg commands run on Enter but prefill with a trailing space on
	// Tab, so the user can add arguments.
	optionalArg bool
}

var builtinCommands = []slashCommand{
	{command: "/help", description: "Show help message"},
	{command: "/clear", description: "Clear chat and start a new session"},
	{command: "/agent", description: "List and switch agents"},
	{command: "/attach", description: "Attach a file to next message", requiresArg: true},
	{command: "/sessions", description: "Browse and resume previous sessions"},
	{command: "/configure", description: "Re-run connection setup"},
	{command: "/connectors", description: "Open connectors in browser"},
	{command: "/settings", description: "Open settings in browser"},
	{command: "/skills", description: "List and reload local skills"},
	{command: "/experiments", description: "List experimental features"},
	{command: "/quit", description: "Exit Onyx CLI"},
}

// builtinNames reports the command names that skills cannot override.
func builtinNames() map[string]bool {
	names := make(map[string]bool, len(builtinCommands)+2)
	for _, sc := range builtinCommands {
		names[sc.command] = true
	}
	// Aliases handled by handleSlashCommand but absent from the menu.
	names["/new"] = true
	names["/resume"] = true
	return names
}

// inputModel manages the text input and slash command menu.
type inputModel struct {
	textInput     textinput.Model
	commands      []slashCommand
	menuVisible   bool
	menuItems     []slashCommand
	menuIndex     int
	attachedFiles []string
	customPrompt  string
	suppressMenu  bool
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
		commands:  builtinCommands,
	}
}

// setSkillCommands appends skill commands to the menu, after the built-ins.
func (m *inputModel) setSkillCommands(entries []slashCommand) {
	commands := make([]slashCommand, 0, len(builtinCommands)+len(entries))
	commands = append(commands, builtinCommands...)
	commands = append(commands, entries...)
	m.commands = commands
}

func (m inputModel) update(msg tea.Msg) (inputModel, tea.Cmd) {
	if keyMsg, ok := msg.(tea.KeyPressMsg); ok {
		return m.handleKey(keyMsg)
	}

	var cmd tea.Cmd
	m.textInput, cmd = m.textInput.Update(msg)
	m = m.updateMenu()
	return m, cmd
}

func (m inputModel) handleKey(msg tea.KeyPressMsg) (inputModel, tea.Cmd) {
	switch msg.String() {
	case "up":
		if m.menuVisible && m.menuIndex > 0 {
			m.menuIndex--
			return m, nil
		}
	case "down":
		if m.menuVisible && m.menuIndex < len(m.menuItems)-1 {
			m.menuIndex++
			return m, nil
		}
	case "tab":
		if m.menuVisible && len(m.menuItems) > 0 {
			item := m.menuItems[m.menuIndex]
			value := item.command
			if item.requiresArg || item.optionalArg {
				value += " "
			}
			m.textInput.SetValue(value)
			m.textInput.SetCursor(len(value))
			m.menuVisible = false
			return m, nil
		}
	case "enter":
		if m.menuVisible && len(m.menuItems) > 0 {
			item := m.menuItems[m.menuIndex]
			cmd := item.command
			if item.requiresArg {
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

	case "esc":
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
	if m.suppressMenu {
		m.menuVisible = false
		return m
	}
	val := strings.TrimSpace(m.textInput.Value())
	if strings.HasPrefix(val, "/") && !strings.Contains(val, " ") {
		needle := strings.ToLower(val)
		var filtered []slashCommand
		for _, sc := range m.commands {
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

func (m *inputModel) setForConfigure(prompt string, placeholder string, echo textinput.EchoMode) {
	m.customPrompt = prompt
	m.suppressMenu = true
	m.textInput.Placeholder = placeholder
	m.textInput.EchoMode = echo
	m.textInput.SetValue("")
}

func (m *inputModel) setCustomPrompt(prompt string) {
	m.customPrompt = prompt
}

func (m *inputModel) resetForChat() {
	m.customPrompt = ""
	m.suppressMenu = false
	m.textInput.EchoMode = textinput.EchoNormal
	m.textInput.Placeholder = "Send a message…"
	m.textInput.SetValue("")
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
	// Only treat as a file drop if it looks explicitly path-like
	if !strings.HasPrefix(cleaned, "/") && !strings.HasPrefix(cleaned, "~") &&
		!strings.HasPrefix(cleaned, "./") && !strings.HasPrefix(cleaned, "../") {
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

	prompt := inputPrompt
	if m.customPrompt != "" {
		prompt = m.customPrompt
	}
	parts = append(parts, prompt+m.textInput.View())
	return strings.Join(parts, "\n")
}
