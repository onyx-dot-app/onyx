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
	apiKeyValidationTimeout        = 15 * time.Second
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
	if len(trimmedKey) > tui.MaxAPIKeyLength {
		return fmt.Errorf("PAT is too long (max %d characters)", tui.MaxAPIKeyLength)
	}

	cfg := config.OnyxCliConfig{
		ServerURL: serverURL,
		APIKey:    trimmedKey,
	}
	client := api.NewClient(cfg)
	ctx, cancel := context.WithTimeout(context.Background(), apiKeyValidationTimeout)
	defer cancel()
	if err := client.TestConnection(ctx); err != nil {
		return apiErrorToExit(err, "PAT validation failed")
	}
	return nil
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

Clients are prompted for their Onyx personal access token (PAT) on connect.
The PAT can also be provided via the ONYX_PAT environment variable to skip the prompt:

  ssh -o SendEnv=ONYX_PAT host -p port

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
				return exitcodes.New(exitcodes.NotConfigured, "server URL is not configured\n  Run: onyx-cli chat to complete first-time setup")
			}
			if !cmd.Flags().Changed("host-key") {
				if v := os.Getenv(config.EnvSSHHostKey); v != "" {
					keyPath = v
				}
			}
			if rateLimitPerMin <= 0 {
				return exitcodes.New(exitcodes.BadRequest, "--rate-limit-per-minute must be > 0")
			}
			if rateLimitBurst <= 0 {
				return exitcodes.New(exitcodes.BadRequest, "--rate-limit-burst must be > 0")
			}
			if rateLimitCache <= 0 {
				return exitcodes.New(exitcodes.BadRequest, "--rate-limit-cache must be > 0")
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
						envErr = fmt.Sprintf("PAT from ONYX_PAT environment variable is invalid: %s", err.Error())
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
					return tui.NewModel(cfg, api.NewClient(cfg)), []tea.ProgramOption{
						tea.WithAltScreen(),
						tea.WithMouseCellMotion(),
					}
				}

				// No valid env key — show auth prompt, then transition
				// to the TUI within the same bubbletea program.
				return tui.NewServeModel(serverCfg, envErr, validateAPIKey), []tea.ProgramOption{
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
