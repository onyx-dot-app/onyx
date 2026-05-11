package tui

import (
	"context"
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
)

type configStep int

const (
	configStepURL configStep = iota
	configStepAPIKey
	configStepTesting
)

type configState struct {
	step      configStep
	serverURL string
	apiKey    string
}

// ConfigTestResultMsg carries the result of an async connection test.
type ConfigTestResultMsg struct {
	Err error
}

func enterConfigureMode(m Model) (Model, tea.Cmd) {
	m.configState = &configState{
		step:      configStepURL,
		serverURL: m.config.ServerURL,
		apiKey:    m.config.APIKey,
	}
	m.viewport.addInfo("Configure connection (Esc to cancel)")
	setConfigureInput(&m, configStepURL, m.config.ServerURL)
	return m, nil
}

func handleConfigureSubmit(m Model, text string) (Model, tea.Cmd) {
	if m.configState == nil {
		return m, nil
	}

	switch m.configState.step {
	case configStepURL:
		url := text
		if url == "" {
			url = m.configState.serverURL
		}
		if !strings.HasPrefix(url, "http://") && !strings.HasPrefix(url, "https://") {
			m.viewport.addWarning("URL must start with http:// or https://")
			return m, nil
		}
		m.configState.serverURL = strings.TrimRight(url, "/")
		m.configState.step = configStepAPIKey
		m.viewport.addInfo("Server: " + m.configState.serverURL)
		setConfigureInput(&m, configStepAPIKey, m.config.APIKey)
		return m, nil

	case configStepAPIKey:
		key := text
		if key == "" {
			key = m.configState.apiKey
		}
		if key == "" {
			m.viewport.addWarning("API key is required.")
			return m, nil
		}
		m.configState.apiKey = key
		m.configState.step = configStepTesting
		setConfigureInput(&m, configStepTesting, "")

		serverURL := m.configState.serverURL
		apiKey := m.configState.apiKey
		return m, func() tea.Msg {
			testCfg := config.OnyxCliConfig{
				ServerURL: serverURL,
				APIKey:    apiKey,
			}
			client := api.NewClient(testCfg)
			return ConfigTestResultMsg{Err: client.TestConnection(context.Background())}
		}

	case configStepTesting:
		return m, nil
	}

	return m, nil
}

func handleConfigTestResult(m Model, msg ConfigTestResultMsg) (Model, tea.Cmd) {
	if m.configState == nil {
		return m, nil
	}

	if msg.Err != nil {
		m.viewport.addError("Connection failed: " + msg.Err.Error())
		m.viewport.addInfo("Run /configure to try again.")
		resetConfigureInput(&m)
		m.configState = nil
		return m, nil
	}

	m.config.ServerURL = m.configState.serverURL
	m.config.APIKey = m.configState.apiKey
	if err := config.Save(m.config); err != nil {
		m.viewport.addError("Could not save config: " + err.Error())
		resetConfigureInput(&m)
		m.configState = nil
		return m, nil
	}

	m.client = api.NewClient(m.config)
	m.viewport.addInfo("Connected and authenticated. Configuration saved.")
	m.status.setServer(m.config.ServerURL)

	resetConfigureInput(&m)
	m.configState = nil
	return m, loadAgentsCmd(m.client)
}

func cancelConfigure(m Model) (Model, tea.Cmd) {
	m.viewport.addInfo("Configuration cancelled.")
	resetConfigureInput(&m)
	m.configState = nil
	return m, nil
}

func setConfigureInput(m *Model, step configStep, defaultVal string) {
	m.input.suppressMenu = true
	m.input.textInput.SetValue("")

	switch step {
	case configStepURL:
		m.input.customPrompt = infoStyle.Render("Server URL ") + dimInfoStyle.Render("❯") + " "
		m.input.textInput.Placeholder = defaultVal
		m.input.textInput.EchoMode = textinput.EchoNormal

	case configStepAPIKey:
		prompt := infoStyle.Render("API key ")
		if defaultVal != "" {
			prompt += dimInfoStyle.Render("[keep existing] ")
		}
		m.input.customPrompt = prompt + dimInfoStyle.Render("❯") + " "
		m.input.textInput.Placeholder = ""
		m.input.textInput.EchoMode = textinput.EchoPassword

	case configStepTesting:
		m.input.customPrompt = dimInfoStyle.Render("  Testing connection…")
		m.input.textInput.Placeholder = ""
		m.input.textInput.EchoMode = textinput.EchoNormal
	}
}

func resetConfigureInput(m *Model) {
	m.input.customPrompt = ""
	m.input.suppressMenu = false
	m.input.textInput.EchoMode = textinput.EchoNormal
	m.input.textInput.Placeholder = "Send a message…"
	m.input.textInput.SetValue("")
}
