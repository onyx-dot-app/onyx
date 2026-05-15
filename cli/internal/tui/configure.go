package tui

import (
	"context"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
)

type startMode int

const (
	startNormal   startMode = iota
	startFirstRun
)

const configTestTimeout = 10 * time.Second

type configStep int

const (
	configStepURL configStep = iota
	configStepAPIKey
	configStepTesting
)

type configState struct {
	step       configStep
	serverURL  string
	apiKey     string
	cancelTest context.CancelFunc
	spinner    spinner.Model
}

func enterConfigureMode(m Model) (Model, tea.Cmd) {
	if m.isStreaming {
		m.viewport.addWarning("Cannot configure while streaming. Press Esc to cancel generation first.")
		return m, nil
	}
	if m.viewport.pickerActive {
		m.viewport.addWarning("Close the current selection first.")
		return m, nil
	}

	m.configState = &configState{
		step:      configStepURL,
		serverURL: m.config.ServerURL,
		apiKey:    m.config.APIKey,
	}
	m.viewport.addInfo("Configure connection (Enter keeps current value, Esc to cancel)")
	m.input.setForConfigure(configURLPrompt(), m.config.ServerURL, textinput.EchoNormal)
	return m, nil
}

func (m Model) handleConfigureSubmit(text string) (Model, tea.Cmd) {
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
		m.input.setForConfigure(
			configAPIKeyPrompt(m.configState.apiKey != ""),
			"",
			textinput.EchoPassword,
		)
		return m, nil

	case configStepAPIKey:
		key := text
		if key == "" {
			key = m.configState.apiKey
		}
		if key == "" {
			m.viewport.addWarning("Personal access token is required.")
			return m, nil
		}
		m.configState.apiKey = key
		m.configState.step = configStepTesting

		s := spinner.New()
		s.Spinner = spinner.Dot
		s.Style = lipgloss.NewStyle().Foreground(accentColor)
		m.configState.spinner = s
		m.input.setForConfigure(configTestingPrompt(s.View()), "", textinput.EchoNormal)

		ctx, cancel := context.WithTimeout(context.Background(), configTestTimeout)
		m.configState.cancelTest = cancel

		serverURL := m.configState.serverURL
		apiKey := m.configState.apiKey
		testCmd := func() tea.Msg {
			defer cancel()
			testCfg := config.OnyxCliConfig{
				ServerURL: serverURL,
				APIKey:    apiKey,
			}
			client := api.NewClient(testCfg)
			return ConfigTestResultMsg{Err: client.TestConnection(ctx)}
		}

		return m, tea.Batch(m.configState.spinner.Tick, testCmd)

	case configStepTesting:
		return m, nil
	}

	return m, nil
}

func (m Model) handleConfigTestResult(msg ConfigTestResultMsg) (Model, tea.Cmd) {
	if m.configState == nil {
		return m, nil
	}

	if msg.Err != nil {
		m.viewport.addError("Connection failed: " + msg.Err.Error())
		m.configState.step = configStepURL
		m.configState.cancelTest = nil
		m.input.setForConfigure(configURLPrompt(), m.configState.serverURL, textinput.EchoNormal)
		return m, nil
	}

	m.config.ServerURL = m.configState.serverURL
	m.config.APIKey = m.configState.apiKey

	if err := config.Save(m.config); err != nil {
		m.viewport.addError("Could not save config: " + err.Error())
		m.configState.step = configStepURL
		m.configState.cancelTest = nil
		m.input.setForConfigure(configURLPrompt(), m.configState.serverURL, textinput.EchoNormal)
		return m, nil
	}

	m.client = api.NewClient(m.config)
	m.viewport.addInfo("Connected to " + m.config.ServerURL + ". Configuration saved.")
	m.status.setServer(m.config.ServerURL)
	m.startMode = startNormal

	m = m.exitConfigureMode()
	return m, loadAgentsCmd(m.client)
}

func (m Model) handleConfigureSpinnerTick(msg spinner.TickMsg) (Model, tea.Cmd) {
	if m.configState == nil || m.configState.step != configStepTesting {
		return m, nil
	}
	var cmd tea.Cmd
	m.configState.spinner, cmd = m.configState.spinner.Update(msg)
	m.input.setCustomPrompt(configTestingPrompt(m.configState.spinner.View()))
	return m, cmd
}

func (m Model) cancelConfigure() (Model, tea.Cmd) {
	if m.startMode == startFirstRun {
		return m.exitConfigureMode(), tea.Quit
	}
	m.viewport.addInfo("Configuration cancelled.")
	return m.exitConfigureMode(), nil
}

func (m Model) exitConfigureMode() Model {
	if m.configState != nil && m.configState.cancelTest != nil {
		m.configState.cancelTest()
	}
	m.configState = nil
	m.input.resetForChat()
	return m
}

func configURLPrompt() string {
	return infoStyle.Render("(1/2) Server URL ") + dimInfoStyle.Render("❯") + " "
}

func configAPIKeyPrompt(hasExisting bool) string {
	prompt := infoStyle.Render("(2/2) Personal access token ")
	if hasExisting {
		prompt += dimInfoStyle.Render("[keep existing] ")
	}
	prompt += dimInfoStyle.Render("❯") + " "
	return prompt
}

func configTestingPrompt(spinnerView string) string {
	return "  " + spinnerView + " Testing connection…"
}
