package tui

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	tea "charm.land/bubbletea/v2"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/browser"
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

	case "/agent":
		if arg != "" {
			return cmdSelectAgent(m, arg)
		}
		return cmdShowAgents(m)

	case "/model":
		if strings.TrimSpace(arg) != "" {
			return cmdSelectModel(m, arg)
		}
		return cmdShowModels(m)

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

	// The new agent may allow a different model set and have its own default.
	return m, loadModelsCmd(m.client, m.agentID, false)
}

func cmdShowModels(m Model) (Model, tea.Cmd) {
	m.viewport.addInfo("Loading models...")
	return m, loadModelsCmd(m.client, m.agentID, true)
}

// cmdSelectModel picks a model by its list number, or by model name / display
// name (case-insensitive, exact match first, then unique prefix). The literal
// "default" clears the override and returns to the agent's own model.
func cmdSelectModel(m Model, arg string) (Model, tea.Cmd) {
	needle := strings.TrimSpace(arg)

	if strings.EqualFold(needle, "default") {
		m.selectedModel = nil
		m.config.DefaultModel = nil
		_ = config.Save(m.config)
		m.refreshModelStatus()
		m.viewport.addInfo("Using the agent's default model: " + m.status.modelName)
		return m, nil
	}

	if len(m.modelOptions) == 0 {
		m.viewport.addWarning("No models loaded yet. Use /model to list them.")
		return m, nil
	}

	if n, err := strconv.Atoi(needle); err == nil {
		if n < 1 || n > len(m.modelOptions) {
			m.viewport.addWarning(fmt.Sprintf("No model %d. Use /model to see the list.", n))
			return m, nil
		}
		return applyModel(m, m.modelOptions[n-1]), nil
	}

	match := findModel(m.modelOptions, needle)
	if match == nil {
		m.viewport.addWarning(fmt.Sprintf("Model %q not found. Use /model to see available models.", needle))
		return m, nil
	}
	return applyModel(m, *match), nil
}

// findModel resolves a name to one model: an exact name or display-name match
// wins, otherwise a prefix match, but only when it is unique.
func findModel(options []models.ModelOption, needle string) *models.ModelOption {
	var prefixMatches []models.ModelOption
	for _, option := range options {
		if strings.EqualFold(option.ModelName, needle) || strings.EqualFold(option.DisplayName, needle) {
			return &option
		}
		if strings.HasPrefix(strings.ToLower(option.ModelName), strings.ToLower(needle)) ||
			strings.HasPrefix(strings.ToLower(option.DisplayName), strings.ToLower(needle)) {
			prefixMatches = append(prefixMatches, option)
		}
	}
	if len(prefixMatches) == 1 {
		return &prefixMatches[0]
	}
	return nil
}

// hasModel reports whether the exact model name is in the list.
func hasModel(options []models.ModelOption, name string) bool {
	for _, option := range options {
		if option.ModelName == name {
			return true
		}
	}
	return false
}

func applyModel(m Model, option models.ModelOption) Model {
	selected := option.SelectedModel
	m.selectedModel = &selected
	m.config.DefaultModel = &selected
	_ = config.Save(m.config)
	m.refreshModelStatus()
	m.viewport.addInfo("Switched to model: " + selected.Label())
	return m
}

// loadModelsCmd fetches the models available to an agent. showPicker asks the
// handler to display the selection list rather than only refresh the status bar.
func loadModelsCmd(client api.ClientAPI, agentID int, showPicker bool) tea.Cmd {
	return func() tea.Msg {
		options, err := client.ListModels(context.Background(), agentID)
		return ModelsLoadedMsg{Options: options, ShowPicker: showPicker, Err: err}
	}
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
