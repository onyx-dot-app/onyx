package tui

import (
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
)

const (
	MaxAPIKeyLength  = 512
	MaxAPIKeyRetries = 5
)

// --- auth prompt (bubbletea model) ---

type authState int

const (
	authInput authState = iota
	authValidating
	authDone
)

// AuthValidatedMsg carries the result of an async API-key validation.
type AuthValidatedMsg struct {
	Key string
	Err error
}

// AuthModel is the bubbletea model for the SSH auth prompt.
type AuthModel struct {
	input        textinput.Model
	serverURL    string
	state        authState
	APIKey       string // set on successful validation
	errMsg       string
	retries      int
	Aborted      bool
	ValidateFunc func(serverURL, apiKey string) error
}

// NewAuthModel creates a new auth prompt model.
func NewAuthModel(serverURL, initialErr string, validateFunc func(string, string) error) AuthModel {
	ti := textinput.New()
	ti.Prompt = "  Personal Access Token: "
	ti.EchoMode = textinput.EchoPassword
	ti.EchoCharacter = '•'
	ti.CharLimit = MaxAPIKeyLength
	ti.Width = 80
	ti.Focus()

	return AuthModel{
		input:        ti,
		serverURL:    serverURL,
		errMsg:       initialErr,
		ValidateFunc: validateFunc,
	}
}

// Update handles messages for the auth prompt.
func (m AuthModel) Update(msg tea.Msg) (AuthModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.input.Width = max(msg.Width-14, 20) // account for prompt width
		return m, nil
	case tea.KeyMsg:
		switch msg.Type {
		case tea.KeyCtrlC, tea.KeyCtrlD:
			m.Aborted = true
			return m, nil
		default:
			if m.state == authValidating {
				return m, nil
			}
		}
		if msg.Type == tea.KeyEnter {
			key := strings.TrimSpace(m.input.Value())
			if key == "" {
				m.errMsg = "No key entered."
				m.retries++
				if m.retries >= MaxAPIKeyRetries {
					m.errMsg = "Too many failed attempts. Disconnecting."
					m.Aborted = true
					return m, nil
				}
				m.input.SetValue("")
				return m, nil
			}
			m.state = authValidating
			m.errMsg = ""
			serverURL := m.serverURL
			validateFunc := m.ValidateFunc
			return m, func() tea.Msg {
				return AuthValidatedMsg{Key: key, Err: validateFunc(serverURL, key)}
			}
		}

	case AuthValidatedMsg:
		if msg.Err != nil {
			m.state = authInput
			m.errMsg = msg.Err.Error()
			m.retries++
			if m.retries >= MaxAPIKeyRetries {
				m.errMsg = "Too many failed attempts. Disconnecting."
				m.Aborted = true
				return m, nil
			}
			m.input.SetValue("")
			return m, m.input.Focus()
		}
		m.APIKey = msg.Key
		m.state = authDone
		return m, nil
	}

	if m.state == authInput {
		var cmd tea.Cmd
		m.input, cmd = m.input.Update(msg)
		return m, cmd
	}
	return m, nil
}

// View renders the auth prompt.
func (m AuthModel) View() string {
	settingsURL := strings.TrimRight(m.serverURL, "/") + "/app/settings/accounts-access"

	var b strings.Builder
	b.WriteString("\n")
	b.WriteString("  \x1b[1;35mOnyx CLI\x1b[0m\n")
	b.WriteString("  \x1b[90m" + m.serverURL + "\x1b[0m\n")
	b.WriteString("\n")
	b.WriteString("  Generate a personal access token (PAT) at:\n")
	b.WriteString("  \x1b[4;34m" + settingsURL + "\x1b[0m\n")
	b.WriteString("\n")
	b.WriteString("  \x1b[90mTip: skip this prompt by passing your PAT via SSH:\x1b[0m\n")
	b.WriteString("  \x1b[90m  export ONYX_PAT=<key>\x1b[0m\n")
	b.WriteString("  \x1b[90m  ssh -o SendEnv=ONYX_PAT <host> -p <port>\x1b[0m\n")
	b.WriteString("\n")

	if m.errMsg != "" {
		b.WriteString("  \x1b[1;31m" + m.errMsg + "\x1b[0m\n\n")
	}

	switch m.state {
	case authDone:
		b.WriteString("  \x1b[32mAuthenticated.\x1b[0m\n")
	case authValidating:
		b.WriteString("  \x1b[90mValidating…\x1b[0m\n")
	default:
		b.WriteString(m.input.View() + "\n")
	}

	return b.String()
}

// --- serve model (wraps auth -> TUI in a single bubbletea program) ---

// ServeModel wraps the auth prompt and the chat TUI into a single
// bubbletea program for SSH serve sessions.
type ServeModel struct {
	auth      AuthModel
	tui       tea.Model
	authed    bool
	serverCfg config.OnyxCliConfig
	width     int
	height    int
}

// NewServeModel creates a new serve model that first shows the auth prompt
// and then transitions to the chat TUI.
func NewServeModel(serverCfg config.OnyxCliConfig, initialErr string, validateFunc func(string, string) error) ServeModel {
	return ServeModel{
		auth:      NewAuthModel(serverCfg.ServerURL, initialErr, validateFunc),
		serverCfg: serverCfg,
	}
}

// Init returns the initial command for the serve model.
func (m ServeModel) Init() tea.Cmd {
	return textinput.Blink
}

// Update handles messages for the serve model.
func (m ServeModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if !m.authed {
		if ws, ok := msg.(tea.WindowSizeMsg); ok {
			m.width = ws.Width
			m.height = ws.Height
		}

		var cmd tea.Cmd
		m.auth, cmd = m.auth.Update(msg)

		if m.auth.Aborted {
			return m, tea.Quit
		}
		if m.auth.APIKey != "" {
			cfg := config.OnyxCliConfig{
				ServerURL:      m.serverCfg.ServerURL,
				APIKey:         m.auth.APIKey,
				DefaultAgentID: m.serverCfg.DefaultAgentID,
			}
			m.tui = NewModel(cfg, api.NewClient(cfg))
			m.authed = true
			w, h := m.width, m.height
			return m, tea.Batch(
				tea.EnterAltScreen,
				tea.EnableMouseCellMotion,
				m.tui.Init(),
				func() tea.Msg { return tea.WindowSizeMsg{Width: w, Height: h} },
			)
		}
		return m, cmd
	}

	var cmd tea.Cmd
	m.tui, cmd = m.tui.Update(msg)
	return m, cmd
}

// View renders the serve model.
func (m ServeModel) View() string {
	if !m.authed {
		return m.auth.View()
	}
	return m.tui.View()
}
