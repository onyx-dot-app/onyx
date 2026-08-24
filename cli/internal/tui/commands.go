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

	return m, nil
}

// modelOption is one selectable model, flattened across providers.
type modelOption struct {
	configID      *int
	name          string // model name sent to the API
	label         string // display name shown in the UI
	providerName  string // provider config name, for name-based override fallback
	providerLabel string // provider display name shown in the UI
	isDefault     bool   // true when this is the workspace default text model
}

// flattenModelOptions turns the provider listing into a flat list of visible
// models, marking the workspace default.
func flattenModelOptions(resp *models.LLMProviderResponse) []modelOption {
	if resp == nil {
		return nil
	}
	var options []modelOption
	for _, provider := range resp.Providers {
		// Only the provider config name works for the name-based override
		// fallback on older servers; the provider type key does not resolve.
		providerName := ""
		if provider.Name != nil {
			providerName = *provider.Name
		}
		for _, mc := range provider.ModelConfigurations {
			if !mc.IsVisible {
				continue
			}
			isDefault := resp.DefaultText != nil &&
				resp.DefaultText.ProviderID == provider.ID &&
				resp.DefaultText.ModelName == mc.Name
			options = append(options, modelOption{
				configID:      mc.ID,
				name:          mc.Name,
				label:         mc.Label(),
				providerName:  providerName,
				providerLabel: provider.ProviderDisplayName,
				isDefault:     isDefault,
			})
		}
	}
	return options
}

func cmdShowModels(m Model) (Model, tea.Cmd) {
	m.viewport.addInfo("Loading models...")
	client := m.client
	return m, func() tea.Msg {
		resp, err := client.ListLLMProviders(context.Background())
		return ModelsLoadedMsg{Response: resp, ShowPicker: true, Err: err}
	}
}

// cmdSelectModel applies the picker selection. idxStr is an index into
// m.llmModels (model names and config IDs are not unique across providers).
func cmdSelectModel(m Model, idxStr string) (Model, tea.Cmd) {
	idx, err := strconv.Atoi(idxStr)
	if err != nil || idx < 0 || idx >= len(m.llmModels) {
		m.viewport.addWarning("Invalid model selection.")
		return m, nil
	}
	opt := m.llmModels[idx]

	override := &models.LLMOverride{
		ModelConfigurationID: opt.configID,
		ModelVersion:         &opt.name,
	}
	if opt.providerName != "" {
		override.ModelProvider = &opt.providerName
	}
	m.modelOverride = override
	m.status.setModel(opt.label)
	m.viewport.addInfo("Switched to model: " + opt.label)
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

// loadModelsCmd fetches LLM providers at startup so the status bar can show
// the current (default) model.
func loadModelsCmd(client api.ClientAPI) tea.Cmd {
	return func() tea.Msg {
		resp, err := client.ListLLMProviders(context.Background())
		return ModelsLoadedMsg{Response: resp, Err: err}
	}
}
