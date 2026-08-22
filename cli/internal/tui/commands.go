package tui

import (
	"context"
	"fmt"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	tea "charm.land/bubbletea/v2"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/browser"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/skills"
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
		return enterConfigureMode(m)

	case "/clear", "/new":
		return cmdNew(m)

	case "/connectors":
		url := config.OnyxWebURL(m.config.ServerURL) + "/admin/indexing/status"
		if browser.OpenBrowser(url) {
			m.viewport.addInfo("Opened " + url + " in browser")
		} else {
			m.viewport.addWarning("Failed to open browser. Visit: " + url)
		}
		return m, nil

	case "/settings":
		url := config.OnyxWebURL(m.config.ServerURL) + "/app/settings/general"
		if browser.OpenBrowser(url) {
			m.viewport.addInfo("Opened " + url + " in browser")
		} else {
			m.viewport.addWarning("Failed to open browser. Visit: " + url)
		}
		return m, nil

	case "/experiments":
		m.viewport.addInfo(config.ExperimentsText(m.config.Features))
		return m, nil

	case "/skills":
		return cmdSkills(m)

	case "/quit":
		return m, tea.Quit

	default:
		if skill, ok := m.skills[strings.TrimPrefix(command, "/")]; ok {
			return cmdRunSkill(m, skill, arg)
		}
		m.viewport.addWarning(fmt.Sprintf("Unknown command: %s. Type /help for available commands.", command))
		return m, nil
	}
}

// cmdRunSkill expands a skill into a prompt and sends it as the next message.
func cmdRunSkill(m Model, skill skills.Skill, arg string) (Model, tea.Cmd) {
	if m.isStreaming {
		m.viewport.addWarning("Wait for the current response to finish.")
		return m, nil
	}
	m.viewport.addInfo("Running skill: " + skill.Name)
	return m.sendMessage(skill.Prompt(arg))
}

// cmdSkills rescans the skill directories and lists what is available.
func cmdSkills(m Model) (Model, tea.Cmd) {
	m = m.loadSkills()

	if len(m.skills) == 0 {
		var b strings.Builder
		b.WriteString("No skills found. Add a SKILL.md file in one of:\n")
		for _, root := range skills.Roots() {
			b.WriteString("  " + filepath.Join(root, ".agents", "skills", "<name>", "SKILL.md") + "\n")
		}
		m.viewport.addInfo(strings.TrimRight(b.String(), "\n"))
		return m, nil
	}

	names := make([]string, 0, len(m.skills))
	for name := range m.skills {
		names = append(names, name)
	}
	sort.Strings(names)

	var b strings.Builder
	fmt.Fprintf(&b, "Skills (%d)\n\n", len(names))
	for _, name := range names {
		skill := m.skills[name]
		fmt.Fprintf(&b, "  /%s", name)
		if skill.Description != "" {
			b.WriteString("  " + skill.Description)
		}
		b.WriteString("\n")
	}
	b.WriteString("\nRun one with /<name> [arguments].")
	m.viewport.addInfo(b.String())
	return m, nil
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
		agents, err := client.ListAgents(context.Background())
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
		fd, err := client.UploadFile(context.Background(), pathStr)
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
		sessions, err := client.ListChatSessions(context.Background())
		return SessionsLoadedMsg{Sessions: sessions, Err: err}
	}
}

func cmdResume(m Model, sessionIDStr string) (Model, tea.Cmd) {
	client := m.client
	return m, func() tea.Msg {
		targetID := sessionIDStr

		// Short prefix — scan the list for a match
		if len(sessionIDStr) < 36 {
			sessions, err := client.ListChatSessions(context.Background())
			if err != nil {
				return SessionResumedMsg{Err: err}
			}
			for _, s := range sessions {
				if strings.HasPrefix(s.ID, sessionIDStr) {
					targetID = s.ID
					break
				}
			}
		}

		detail, err := client.GetChatSession(context.Background(), targetID)
		if err != nil {
			return SessionResumedMsg{Err: fmt.Errorf("session not found: %s", sessionIDStr)}
		}
		return SessionResumedMsg{Detail: detail}
	}
}

// loadAgentsCmd returns a tea.Cmd that loads agents from the API.
func loadAgentsCmd(client api.ClientAPI) tea.Cmd {
	return func() tea.Msg {
		agents, err := client.ListAgents(context.Background())
		return InitDoneMsg{Agents: agents, Err: err}
	}
}
