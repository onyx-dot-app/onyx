package cmd

import (
	"context"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/onboarding"
	"github.com/spf13/cobra"
	"golang.org/x/term"
)

func newConfigureCmd() *cobra.Command {
	var (
		serverURL string
		apiKey    string
		dryRun    bool
	)

	cmd := &cobra.Command{
		Use:   "configure",
		Short: "Configure server URL and API key",
		Long: `Set up the Onyx CLI with your server URL and API key.

When --server-url and --api-key are both provided, the configuration is saved
non-interactively (useful for scripts and AI agents). Otherwise, an interactive
setup wizard is launched.

If --api-key is omitted but stdin has piped data, the API key is read from
stdin. This avoids leaking the key in shell history.

Use --dry-run to test the connection without saving the configuration.`,
		Example: `  onyx-cli configure
  onyx-cli configure --server-url https://my-onyx.com --api-key sk-...
  echo "$ONYX_API_KEY" | onyx-cli configure --server-url https://my-onyx.com
  onyx-cli configure --server-url https://my-onyx.com --api-key sk-... --dry-run`,
		RunE: func(cmd *cobra.Command, args []string) error {
			// If --api-key not provided, try reading from stdin pipe
			if apiKey == "" && !term.IsTerminal(int(os.Stdin.Fd())) {
				data, err := io.ReadAll(os.Stdin)
				if err != nil {
					return fmt.Errorf("failed to read API key from stdin: %w", err)
				}
				apiKey = strings.TrimSpace(string(data))
			}

			if serverURL != "" && apiKey != "" {
				return configureNonInteractive(serverURL, apiKey, dryRun)
			}

			if dryRun {
				return exitcodes.New(exitcodes.BadRequest, "--dry-run requires --server-url and --api-key")
			}

			if serverURL != "" || apiKey != "" {
				return exitcodes.New(exitcodes.BadRequest, "both --server-url and --api-key are required for non-interactive setup\n  Run 'onyx-cli configure' without flags for interactive setup")
			}

			cfg := config.Load()
			onboarding.Run(&cfg)
			return nil
		},
	}

	cmd.Flags().StringVar(&serverURL, "server-url", "", "Onyx server URL (e.g., https://cloud.onyx.app)")
	cmd.Flags().StringVar(&apiKey, "api-key", "", "API key for authentication (or pipe via stdin)")
	cmd.Flags().BoolVar(&dryRun, "dry-run", false, "Test connection without saving config (requires --server-url and --api-key)")

	return cmd
}

func configureNonInteractive(serverURL, apiKey string, dryRun bool) error {
	cfg := config.OnyxCliConfig{
		ServerURL:      serverURL,
		APIKey:         apiKey,
		DefaultAgentID: 0,
	}

	// Preserve existing default agent ID from disk (not env overrides)
	if existing := config.LoadFromDisk(); existing.DefaultAgentID != 0 {
		cfg.DefaultAgentID = existing.DefaultAgentID
	}

	// Test connection
	client := api.NewClient(cfg)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	if err := client.TestConnection(ctx); err != nil {
		return exitcodes.Newf(exitcodes.Unreachable, "connection test failed: %v\n  Check your server URL and API key", err)
	}

	if dryRun {
		fmt.Printf("Server:  %s\n", serverURL)
		fmt.Println("Status:  connected and authenticated")
		fmt.Println("Dry run: config was NOT saved")
		return nil
	}

	if err := config.Save(cfg); err != nil {
		return fmt.Errorf("could not save config: %w", err)
	}

	fmt.Printf("Config:  %s\n", config.ConfigFilePath())
	fmt.Printf("Server:  %s\n", serverURL)
	fmt.Println("Status:  connected and authenticated")
	return nil
}
