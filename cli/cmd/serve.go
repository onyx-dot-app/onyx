package cmd

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

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
	"github.com/onyx-dot-app/onyx/cli/internal/tui"
	"github.com/spf13/cobra"
	"golang.org/x/time/rate"
)

var sessionAPIKeys sync.Map

const (
	defaultServeIdleTimeout        = 15 * time.Minute
	defaultServeMaxSessionTimeout  = 8 * time.Hour
	defaultServeRateLimitPerMinute = 20
	defaultServeRateLimitBurst     = 40
	defaultServeRateLimitCacheSize = 4096
	maxAPIKeyLength                = 256
	apiKeyValidationTimeout        = 15 * time.Second
)

var errAPIKeyTooLong = fmt.Errorf("API key is too long (max %d characters)", maxAPIKeyLength)

// sshWriter wraps an io.Writer and tracks the first write error, allowing
// a sequence of writes to be checked once at the end.
type sshWriter struct {
	w   io.Writer
	err error
}

func (w *sshWriter) print(s string) {
	if w.err == nil {
		_, w.err = fmt.Fprint(w.w, s)
	}
}

func (w *sshWriter) printf(format string, args ...any) {
	if w.err == nil {
		_, w.err = fmt.Fprintf(w.w, format, args...)
	}
}

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
		return errAPIKeyTooLong
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

// readMasked reads input from the SSH session one chunk at a time, echoing '•'
// for each printable character. Handles backspace and skips escape sequences.
func readMasked(w *sshWriter, s ssh.Session) (string, error) {
	var key []byte
	buf := make([]byte, 4096)
	inEscape := false

	for {
		n, err := s.Read(buf)
		if err != nil {
			return "", err
		}
		for i := 0; i < n; i++ {
			b := buf[i]

			if inEscape {
				if (b >= 'A' && b <= 'Z') || (b >= 'a' && b <= 'z') || b == '~' {
					inEscape = false
				}
				continue
			}

			switch {
			case b == 27: // ESC
				inEscape = true
			case b == '\r' || b == '\n':
				return string(key), nil
			case b == 3: // Ctrl+C
				return "", fmt.Errorf("interrupted")
			case b == 4: // Ctrl+D
				return "", fmt.Errorf("quit")
			case b == 127 || b == 8: // Backspace / Delete
				if len(key) > 0 {
					key = key[:len(key)-1]
					w.print("\b \b")
				}
			case b >= 32 && b < 127: // printable ASCII
				if len(key) >= maxAPIKeyLength {
					return "", errAPIKeyTooLong
				}
				key = append(key, b)
				w.print("•")
			}

			if w.err != nil {
				return "", w.err
			}
		}
	}
}

// promptAPIKey shows a login screen and reads the API key interactively.
// Validates the key before returning. Loops on failure so the user can retry.
func promptAPIKey(s ssh.Session, serverURL string) (string, error) {
	settingsURL := strings.TrimRight(serverURL, "/") + "/app/settings/accounts-access"
	w := &sshWriter{w: s}

	w.print("\r\n")
	w.print("  \x1b[1;35mOnyx CLI\x1b[0m\r\n")
	w.printf("  \x1b[90m%s\x1b[0m\r\n", serverURL)
	w.print("\r\n")
	w.print("  Generate an API key at:\r\n")
	w.printf("  \x1b[4;34m%s\x1b[0m\r\n", settingsURL)
	w.print("\r\n")
	w.print("  \x1b[90mTip: skip this prompt by passing your key via SSH:\x1b[0m\r\n")
	w.print("  \x1b[90m  export ONYX_API_KEY=<key>\x1b[0m\r\n")
	w.print("  \x1b[90m  ssh -o SendEnv=ONYX_API_KEY <host> -p <port>\x1b[0m\r\n")
	w.print("\r\n")

	if w.err != nil {
		return "", w.err
	}

	for {
		w.print("  API Key: ")
		if w.err != nil {
			return "", w.err
		}

		key, err := readMasked(w, s)
		if err != nil {
			if errors.Is(err, errAPIKeyTooLong) {
				w.print("\r\n")
				w.printf("  \x1b[33m%s\x1b[0m\r\n\r\n", errAPIKeyTooLong.Error())
				if w.err != nil {
					return "", w.err
				}
				continue
			}
			w.print("\r\n")
			return "", err
		}
		w.print("\r\n")

		key = strings.TrimSpace(key)
		if key == "" {
			w.print("  \x1b[33mNo key entered.\x1b[0m\r\n\r\n")
			if w.err != nil {
				return "", w.err
			}
			continue
		}

		w.print("  \x1b[90mValidating…\x1b[0m")
		if w.err != nil {
			return "", w.err
		}

		err = validateAPIKey(serverURL, key)

		w.print("\r\x1b[2K") // clear "Validating…" line

		if err != nil {
			w.printf("  \x1b[1;31m%s\x1b[0m\r\n\r\n", err.Error())
			if w.err != nil {
				return "", w.err
			}
			continue
		}

		w.print("  \x1b[32mAuthenticated.\x1b[0m\r\n\r\n")
		return key, w.err
	}
}

// authMiddleware prompts for an API key (or reads it from the session env)
// before handing off to the next handler (bubbletea).
func authMiddleware(serverCfg config.OnyxCliConfig) wish.Middleware {
	return func(next ssh.Handler) ssh.Handler {
		return func(s ssh.Session) {
			w := &sshWriter{w: s}
			apiKey := strings.TrimSpace(sessionEnv(s, config.EnvAPIKey))

			if apiKey != "" {
				if err := validateAPIKey(serverCfg.ServerURL, apiKey); err != nil {
					w.print("\r\n")
					w.print("  \x1b[33mThe ONYX_API_KEY provided via SSH environment is invalid.\x1b[0m\r\n")
					w.printf("  \x1b[1;31m%s\x1b[0m\r\n\r\n", err.Error())
					if w.err != nil {
						return
					}
					apiKey = ""
				}
			}

			if apiKey == "" {
				var err error
				apiKey, err = promptAPIKey(s, serverCfg.ServerURL)
				if err != nil {
					return
				}
			}

			sessionAPIKeys.Store(s, apiKey)
			defer sessionAPIKeys.Delete(s)
			next(s)
		}
	}
}

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
already exist.

Example:
  onyx-cli serve --port 2222
  ssh localhost -p 2222`,
		RunE: func(cmd *cobra.Command, args []string) error {
			serverCfg := config.Load()
			if serverCfg.ServerURL == "" {
				return fmt.Errorf("server URL is not configured; run 'onyx-cli configure' first")
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
				apiKey := ""
				if v, ok := sessionAPIKeys.Load(s); ok {
					apiKey = v.(string)
				}

				cfg := config.OnyxCliConfig{
					ServerURL:      serverCfg.ServerURL,
					APIKey:         apiKey,
					DefaultAgentID: serverCfg.DefaultAgentID,
				}

				m := tui.NewModel(cfg)
				return m, []tea.ProgramOption{
					tea.WithAltScreen(),
					tea.WithMouseCellMotion(),
				}
			}

			serverOptions := []ssh.Option{
				wish.WithAddress(addr),
				wish.WithHostKeyPath(keyPath),
				wish.WithMiddleware(
					bubbletea.Middleware(handler),
					authMiddleware(serverCfg),
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

			go func() {
				if err := s.ListenAndServe(); err != nil && !errors.Is(err, ssh.ErrServerClosed) {
					log.Error("SSH server failed", "error", err)
					done <- nil
				}
			}()

			<-done
			log.Info("Shutting down SSH server")
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			return s.Shutdown(ctx)
		},
	}

	cmd.Flags().StringVar(&host, "host", "localhost", "Host address to bind to")
	cmd.Flags().IntVarP(&port, "port", "p", 2222, "Port to listen on")
	cmd.Flags().StringVar(&keyPath, "host-key", ".ssh/onyx_serve_ed25519",
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
