package tui

import (
	"fmt"
	"strconv"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/util"
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

	case "/agent":
		if arg != "" {
			return cmdSelectAgent(m, arg)
		}
		return cmdShowAgents(m)

	case "/attach":
		return cmdAttach(m, arg)

	case "/sessions", "/resume":
		if strings.TrimSpace(arg) != "" {
			return cmdResume(m, arg)
		}
		return cmdSessions(m)

	case "/configure":
		m.viewport.addInfo("Run 'onyx-cli configure' to change connection settings.")
		return m, nil

	case "/clear", "/new":
		return cmdNew(m)

	case "/connectors":
		url := m.config.ServerURL + "/admin/indexing/status"
		if util.OpenBrowser(url) {
			m.viewport.addInfo("Opened " + url + " in browser")
		} else {
			m.viewport.addWarning("Failed to open browser. Visit: " + url)
		}
		return m, nil

	case "/settings":
		url := m.config.ServerURL + "/app/settings/general"
		if util.OpenBrowser(url) {
			m.viewport.addInfo("Opened " + url + " in browser")
		} else {
			m.viewport.addWarning("Failed to open browser. Visit: " + url)
		}
		return m, nil

	case "/quit":
		return m, tea.Quit

	default:
		m.viewport.addWarning(fmt.Sprintf("Unknown command: %s. Type /help for available commands.", command))
		return m, nil
	}
}

func cmdNew(m Model) (Model, tea.Cmd) {
	if m.isStreaming {
		m, _ = m.cancelStream()
	}
	m.chatSessionID = nil
	parentID := -1
	m.parentMessageID = &parentID
	m.needsRename = false
	m.citations = nil
	m.viewport.clearAll()
	// Re-add splash as a scrollable entry
	viewportHeight := m.viewportHeight()
	if viewportHeight < 1 {
		viewportHeight = m.height
	}
	m.viewport.addSplash(viewportHeight)
	m.status.setSession("")
	return m, nil
}

func cmdShowAgents(m Model) (Model, tea.Cmd) {
	m.viewport.addInfo("Loading agents...")
	client := m.client
	return m, func() tea.Msg {
		agents, err := client.ListAgents()
		return AgentsLoadedMsg{Agents: agents, Err: err}
	}
}

func cmdSelectAgent(m Model, idStr string) (Model, tea.Cmd) {
	pid, err := strconv.Atoi(strings.TrimSpace(idStr))
	if err != nil {
		m.viewport.addWarning("Invalid agent ID. Use a number.")
		return m, nil
	}

	var target *models.AgentSummary
	for i := range m.agents {
		if m.agents[i].ID == pid {
			target = &m.agents[i]
			break
		}
	}

	if target == nil {
		m.viewport.addWarning(fmt.Sprintf("Agent %d not found. Use /agent to see available agents.", pid))
		return m, nil
	}

	m.agentID = target.ID
	m.agentName = target.Name
	m.status.setAgent(target.Name)
	m.viewport.addInfo("Switched to agent: " + target.Name)

	// Save preference
	m.config.DefaultAgentID = target.ID
	_ = config.Save(m.config)

	return m, nil
}

func cmdAttach(m Model, pathStr string) (Model, tea.Cmd) {
	if pathStr == "" {
		m.viewport.addWarning("Usage: /attach <file_path>")
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

// loadAgentsCmd returns a tea.Cmd that loads agents from the API.
func loadAgentsCmd(client *api.Client) tea.Cmd {
	return func() tea.Msg {
		agents, err := client.ListAgents()
		return InitDoneMsg{Agents: agents, Err: err}
	}
}
