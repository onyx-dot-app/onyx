package tui

import (
	"fmt"
	"os/exec"
	"runtime"
	"strconv"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

// handleSlashCommand dispatches slash commands and returns updated model + cmd.
func handleSlashCommand(m Model, text string) (Model, tea.Cmd) {
	parts := strings.SplitN(text, " ", 2)
	command := strings.ToLower(parts[0])
	arg := ""
	if len(parts) > 1 {
		arg = parts[1]
	}

	switch command {
	case "/help":
		m.viewport.addInfo(helpText)
		return m, nil

	case "/new":
		return cmdNew(m)

	case "/persona", "/assistant":
		if arg != "" {
			return cmdSelectPersona(m, arg)
		}
		return cmdShowPersonas(m)

	case "/attach":
		return cmdAttach(m, arg)

	case "/sessions":
		return cmdSessions(m)

	case "/resume":
		return cmdResume(m, arg)

	case "/configure":
		m.viewport.addInfo("Run 'onyx-cli configure' to change connection settings.")
		return m, nil

	case "/clear":
		m.viewport.clearDisplay()
		return m, nil

	case "/connectors":
		url := m.config.ServerURL + "/admin/indexing/status"
		openBrowser(url)
		m.viewport.addInfo("Opened " + url + " in browser")
		return m, nil

	case "/settings":
		url := m.config.ServerURL + "/app/settings/general"
		openBrowser(url)
		m.viewport.addInfo("Opened " + url + " in browser")
		return m, nil

	case "/quit":
		return m, tea.Quit

	default:
		m.viewport.addInfo(fmt.Sprintf("Unknown command: %s. Type /help for available commands.", command))
		return m, nil
	}
}

func cmdNew(m Model) (Model, tea.Cmd) {
	m.chatSessionID = nil
	parentID := -1
	m.parentMessageID = &parentID
	m.needsRename = false
	m.citations = nil
	m.viewport.clearAll()
	// Re-add splash as a scrollable entry
	viewportHeight := m.height - 4
	if viewportHeight < 1 {
		viewportHeight = m.height
	}
	m.viewport.addSplash(viewportHeight)
	m.status.setSession("")
	return m, nil
}

func cmdShowPersonas(m Model) (Model, tea.Cmd) {
	if len(m.personas) == 0 {
		m.viewport.addInfo("No assistants available. Try again after loading completes.")
		return m, nil
	}

	m.viewport.addInfo("Available Assistants")
	for _, p := range m.personas {
		marker := ""
		if p.ID == m.personaID {
			marker = " *"
		}
		desc := p.Description
		if len(desc) > 60 {
			desc = desc[:60] + "..."
		}
		if desc != "" {
			desc = " - " + desc
		}
		m.viewport.addInfo(fmt.Sprintf("  %d: %s%s%s", p.ID, p.Name, desc, marker))
	}
	m.viewport.addInfo("Use /persona <id> to switch. Example: /persona 1")
	return m, nil
}

func cmdSelectPersona(m Model, idStr string) (Model, tea.Cmd) {
	pid, err := strconv.Atoi(strings.TrimSpace(idStr))
	if err != nil {
		m.viewport.addInfo("Invalid persona ID. Use a number.")
		return m, nil
	}

	var target *models.PersonaSummary
	for i := range m.personas {
		if m.personas[i].ID == pid {
			target = &m.personas[i]
			break
		}
	}

	if target == nil {
		m.viewport.addInfo(fmt.Sprintf("Persona %d not found. Use /persona to see available assistants.", pid))
		return m, nil
	}

	m.personaID = target.ID
	m.personaName = target.Name
	m.status.setPersona(target.Name)
	m.viewport.addInfo("Switched to assistant: " + target.Name)

	// Save preference
	m.config.DefaultPersonaID = target.ID
	_ = config.Save(m.config)

	return m, nil
}

func cmdAttach(m Model, pathStr string) (Model, tea.Cmd) {
	if pathStr == "" {
		m.viewport.addInfo("Usage: /attach <file_path>")
		return m, nil
	}

	m.viewport.addInfo("Uploading " + pathStr + "...")

	client := m.client
	return m, func() tea.Msg {
		fd, err := client.UploadFile(pathStr)
		if err != nil {
			return FileUploadedMsg{Err: err, FileName: pathStr}
		}
		return FileUploadedMsg{Descriptor: fd, FileName: pathStr}
	}
}

func cmdSessions(m Model) (Model, tea.Cmd) {
	m.viewport.addInfo("Loading sessions...")
	client := m.client
	return m, func() tea.Msg {
		sessions, err := client.ListChatSessions()
		return SessionsLoadedMsg{Sessions: sessions, Err: err}
	}
}

func cmdResume(m Model, sessionIDStr string) (Model, tea.Cmd) {
	if sessionIDStr == "" {
		m.viewport.addInfo("Usage: /resume <session_id>")
		return m, nil
	}

	client := m.client
	return m, func() tea.Msg {
		// Try to find session by prefix match
		sessions, err := client.ListChatSessions()
		if err != nil {
			return SessionResumedMsg{Err: err}
		}

		var targetID string
		for _, s := range sessions {
			if strings.HasPrefix(s.ID, sessionIDStr) {
				targetID = s.ID
				break
			}
		}

		if targetID == "" {
			// Try as full UUID
			targetID = sessionIDStr
		}

		detail, err := client.GetChatSession(targetID)
		if err != nil {
			return SessionResumedMsg{Err: fmt.Errorf("session not found: %s", sessionIDStr)}
		}
		return SessionResumedMsg{Detail: detail}
	}
}

func openBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", url)
	case "linux":
		cmd = exec.Command("xdg-open", url)
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	}
	if cmd != nil {
		_ = cmd.Start()
	}
}

// loadPersonasCmd returns a tea.Cmd that loads personas from the API.
func loadPersonasCmd(client *api.Client) tea.Cmd {
	return func() tea.Msg {
		personas, err := client.ListPersonas()
		return InitDoneMsg{Personas: personas, Err: err}
	}
}
