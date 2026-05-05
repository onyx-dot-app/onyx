package cmd

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/log"
	"github.com/charmbracelet/ssh"
	"github.com/charmbracelet/wish"
	"github.com/charmbracelet/wish/activeterm"
	"github.com/charmbracelet/wish/bubbletea"
	"github.com/charmbracelet/wish/logging"
	"github.com/charmbracelet/wish/ratelimiter"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/tui"
	"github.com/spf13/cobra"
	"golang.org/x/time/rate"
)

const (
	defaultServeIdleTimeout        = 15 * time.Minute
	defaultServeMaxSessionTimeout  = 8 * time.Hour
	defaultServeRateLimitPerMinute = 20
	defaultServeRateLimitBurst     = 40
	defaultServeRateLimitCacheSize = 4096
	maxAPIKeyLength                = 512
	apiKeyValidationTimeout        = 15 * time.Second
	maxAPIKeyRetries               = 5
)

func sessionEnv(s ssh.Session, key string) string {
	prefix := key + "="
	for _, env := range s.Environ() {
		if strings.HasPrefix(env, prefix) {
			return env[len(prefix):]
		}
	}
	return ""
}

func validateAPIKey(serverURL string, apiKey string) error {
	trimmedKey := strings.TrimSpace(apiKey)
	if len(trimmedKey) > maxAPIKeyLength {
		return fmt.Errorf("API key is too long (max %d characters)", maxAPIKeyLength)
	}

	cfg := config.OnyxCliConfig{
		ServerURL: serverURL,
		APIKey:    trimmedKey,
	}
	client := api.NewClient(cfg)
	ctx, cancel := context.WithTimeout(context.Background(), apiKeyValidationTimeout)
	defer cancel()
	return client.TestConnection(ctx)
}

// --- auth prompt (bubbletea model) ---

type authState int

const (
	authInput authState = iota
	authValidating
	authDone
)

type authValidatedMsg struct {
	key string
	err error
}

type authModel struct {
	input     textinput.Model
	serverURL string
	state     authState
	apiKey    string // set on successful validation
	errMsg    string
	retries   int
	aborted   bool
}

func newAuthModel(serverURL, initialErr string) authModel {
	ti := textinput.New()
	ti.Prompt = "  API Key: "
	ti.EchoMode = textinput.EchoPassword
	ti.EchoCharacter = '•'
	ti.CharLimit = maxAPIKeyLength
	ti.Width = 80
	ti.Focus()

	return authModel{
		input:     ti,
		serverURL: serverURL,
		errMsg:    initialErr,
	}
}

func (m authModel) Update(msg tea.Msg) (authModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.input.Width = max(msg.Width-14, 20) // account for prompt width
		return m, nil
	case tea.KeyMsg:
		switch msg.Type {
		case tea.KeyCtrlC, tea.KeyCtrlD:
			m.aborted = true
			return m, nil
		default:
			if m.state == authValidating {
				return m, nil
			}
		}
		switch msg.Type {
		case tea.KeyEnter:
			key := strings.TrimSpace(m.input.Value())
			if key == "" {
				m.errMsg = "No key entered."
				m.retries++
				if m.retries >= maxAPIKeyRetries {
					m.errMsg = "Too many failed attempts. Disconnecting."
					m.aborted = true
					return m, nil
				}
				m.input.SetValue("")
				return m, nil
			}
			m.state = authValidating
			m.errMsg = ""
			serverURL := m.serverURL
			return m, func() tea.Msg {
				return authValidatedMsg{key: key, err: validateAPIKey(serverURL, key)}
			}
		}

	case authValidatedMsg:
		if msg.err != nil {
			m.state = authInput
			m.errMsg = msg.err.Error()
			m.retries++
			if m.retries >= maxAPIKeyRetries {
				m.errMsg = "Too many failed attempts. Disconnecting."
				m.aborted = true
				return m, nil
			}
			m.input.SetValue("")
			return m, m.input.Focus()
		}
		m.apiKey = msg.key
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

func (m authModel) View() string {
	settingsURL := strings.TrimRight(m.serverURL, "/") + "/app/settings/accounts-access"

	var b strings.Builder
	b.WriteString("\n")
	b.WriteString("  \x1b[1;35mOnyx CLI\x1b[0m\n")
	b.WriteString("  \x1b[90m" + m.serverURL + "\x1b[0m\n")
	b.WriteString("\n")
	b.WriteString("  Generate an API key at:\n")
	b.WriteString("  \x1b[4;34m" + settingsURL + "\x1b[0m\n")
	b.WriteString("\n")
	b.WriteString("  \x1b[90mTip: skip this prompt by passing your key via SSH:\x1b[0m\n")
	b.WriteString("  \x1b[90m  export ONYX_API_KEY=<key>\x1b[0m\n")
	b.WriteString("  \x1b[90m  ssh -o SendEnv=ONYX_API_KEY <host> -p <port>\x1b[0m\n")
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

// --- serve model (wraps auth → TUI in a single bubbletea program) ---

type serveModel struct {
	auth      authModel
	tui       tea.Model
	authed    bool
	serverCfg config.OnyxCliConfig
	width     int
	height    int
}

func newServeModel(serverCfg config.OnyxCliConfig, initialErr string) serveModel {
	return serveModel{
		auth:      newAuthModel(serverCfg.ServerURL, initialErr),
		serverCfg: serverCfg,
	}
}

func (m serveModel) Init() tea.Cmd {
	return textinput.Blink
}

func (m serveModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if !m.authed {
		if ws, ok := msg.(tea.WindowSizeMsg); ok {
			m.width = ws.Width
			m.height = ws.Height
		}

		var cmd tea.Cmd
		m.auth, cmd = m.auth.Update(msg)

		if m.auth.aborted {
			return m, tea.Quit
		}
		if m.auth.apiKey != "" {
			cfg := config.OnyxCliConfig{
				ServerURL:      m.serverCfg.ServerURL,
				APIKey:         m.auth.apiKey,
				DefaultAgentID: m.serverCfg.DefaultAgentID,
			}
			m.tui = tui.NewModel(cfg)
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

func (m serveModel) View() string {
	if !m.authed {
		return m.auth.View()
	}
	return m.tui.View()
}

// --- serve command ---

func newServeCmd() *cobra.Command {
	var (
		host              string
		port              int
		keyPath           string
		idleTimeout       time.Duration
		maxSessionTimeout time.Duration
		rateLimitPerMin   int
		rateLimitBurst    int
		rateLimitCache    int
	)

	cmd := &cobra.Command{
		Use:   "serve",
		Short: "Serve the Onyx TUI over SSH",
		Long: `Start an SSH server that presents the interactive Onyx chat TUI to
connecting clients. Each SSH session gets its own independent TUI instance.

Clients are prompted for their Onyx API key on connect. The key can also be
provided via the ONYX_API_KEY environment variable to skip the prompt:

  ssh -o SendEnv=ONYX_API_KEY host -p port

The server URL is taken from the server operator's config. The server
auto-generates an Ed25519 host key on first run if the key file does not
already exist. The host key path can also be set via the ONYX_SSH_HOST_KEY
environment variable (the --host-key flag takes precedence).`,
		Example: `  onyx-cli serve --port 2222
  ssh localhost -p 2222
  onyx-cli serve --host 0.0.0.0 --port 2222
  onyx-cli serve --idle-timeout 30m --max-session-timeout 2h`,
		RunE: func(cmd *cobra.Command, args []string) error {
			serverCfg := config.Load()
			if serverCfg.ServerURL == "" {
				return exitcodes.New(exitcodes.NotConfigured, "server URL is not configured\n  Run: onyx-cli configure")
			}
			if !cmd.Flags().Changed("host-key") {
				if v := os.Getenv(config.EnvSSHHostKey); v != "" {
					keyPath = v
				}
			}
			if rateLimitPerMin <= 0 {
				return fmt.Errorf("--rate-limit-per-minute must be > 0")
			}
			if rateLimitBurst <= 0 {
				return fmt.Errorf("--rate-limit-burst must be > 0")
			}
			if rateLimitCache <= 0 {
				return fmt.Errorf("--rate-limit-cache must be > 0")
			}

			addr := net.JoinHostPort(host, fmt.Sprintf("%d", port))
			connectionLimiter := ratelimiter.NewRateLimiter(
				rate.Limit(float64(rateLimitPerMin)/60.0),
				rateLimitBurst,
				rateLimitCache,
			)

			handler := func(s ssh.Session) (tea.Model, []tea.ProgramOption) {
				apiKey := strings.TrimSpace(sessionEnv(s, config.EnvAPIKey))
				var envErr string

				if apiKey != "" {
					if err := validateAPIKey(serverCfg.ServerURL, apiKey); err != nil {
						envErr = fmt.Sprintf("ONYX_API_KEY from SSH environment is invalid: %s", err.Error())
						apiKey = ""
					}
				}

				if apiKey != "" {
					// Env key is valid — go straight to the TUI.
					cfg := config.OnyxCliConfig{
						ServerURL:      serverCfg.ServerURL,
						APIKey:         apiKey,
						DefaultAgentID: serverCfg.DefaultAgentID,
					}
					return tui.NewModel(cfg), []tea.ProgramOption{
						tea.WithAltScreen(),
						tea.WithMouseCellMotion(),
					}
				}

				// No valid env key — show auth prompt, then transition
				// to the TUI within the same bubbletea program.
				return newServeModel(serverCfg, envErr), []tea.ProgramOption{
					tea.WithMouseCellMotion(),
				}
			}

			serverOptions := []ssh.Option{
				wish.WithAddress(addr),
				wish.WithHostKeyPath(keyPath),
				wish.WithMiddleware(
					bubbletea.Middleware(handler),
					activeterm.Middleware(),
					ratelimiter.Middleware(connectionLimiter),
					logging.Middleware(),
				),
			}
			if idleTimeout > 0 {
				serverOptions = append(serverOptions, wish.WithIdleTimeout(idleTimeout))
			}
			if maxSessionTimeout > 0 {
				serverOptions = append(serverOptions, wish.WithMaxTimeout(maxSessionTimeout))
			}

			s, err := wish.NewServer(serverOptions...)
			if err != nil {
				return fmt.Errorf("could not create SSH server: %w", err)
			}

			done := make(chan os.Signal, 1)
			signal.Notify(done, os.Interrupt, syscall.SIGTERM)

			log.Info("Starting Onyx SSH server", "addr", addr)
			log.Info("Connect with", "cmd", fmt.Sprintf("ssh %s -p %d", host, port))

			errCh := make(chan error, 1)
			go func() {
				if err := s.ListenAndServe(); err != nil && !errors.Is(err, ssh.ErrServerClosed) {
					log.Error("SSH server failed", "error", err)
					errCh <- err
				}
			}()

			var serverErr error
			select {
			case <-done:
			case serverErr = <-errCh:
			}

			signal.Stop(done)
			log.Info("Shutting down SSH server")
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			if shutdownErr := s.Shutdown(ctx); shutdownErr != nil {
				return errors.Join(serverErr, shutdownErr)
			}
			return serverErr
		},
	}

	cmd.Flags().StringVar(&host, "host", "localhost", "Host address to bind to")
	cmd.Flags().IntVarP(&port, "port", "p", 2222, "Port to listen on")
	cmd.Flags().StringVar(&keyPath, "host-key", filepath.Join(config.ConfigDir(), "host_ed25519"),
		"Path to SSH host key (auto-generated if missing)")
	cmd.Flags().DurationVar(
		&idleTimeout,
		"idle-timeout",
		defaultServeIdleTimeout,
		"Disconnect idle clients after this duration (set 0 to disable)",
	)
	cmd.Flags().DurationVar(
		&maxSessionTimeout,
		"max-session-timeout",
		defaultServeMaxSessionTimeout,
		"Maximum lifetime of a client session (set 0 to disable)",
	)
	cmd.Flags().IntVar(
		&rateLimitPerMin,
		"rate-limit-per-minute",
		defaultServeRateLimitPerMinute,
		"Per-IP connection rate limit (new sessions per minute)",
	)
	cmd.Flags().IntVar(
		&rateLimitBurst,
		"rate-limit-burst",
		defaultServeRateLimitBurst,
		"Per-IP burst limit for connection attempts",
	)
	cmd.Flags().IntVar(
		&rateLimitCache,
		"rate-limit-cache",
		defaultServeRateLimitCacheSize,
		"Maximum number of IP limiter entries tracked in memory",
	)

	return cmd
}
