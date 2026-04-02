package cmd

import (
	"context"
	"fmt"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/onboarding"
	"github.com/spf13/cobra"
)

func newConfigureCmd() *cobra.Command {
	var (
		serverURL string
		apiKey    string
	)

	cmd := &cobra.Command{
		Use:   "configure",
		Short: "Configure server URL and API key",
		Long: `Set up the Onyx CLI with your server URL and API key.

When --server-url and --api-key are both provided, the configuration is saved
non-interactively (useful for scripts and AI agents). Otherwise, an interactive
setup wizard is launched.`,
		Example: `  onyx-cli configure
  onyx-cli configure --server-url https://my-onyx.com --api-key sk-...`,
		RunE: func(cmd *cobra.Command, args []string) error {
			if serverURL != "" && apiKey != "" {
				return configureNonInteractive(serverURL, apiKey)
			}

			if serverURL != "" || apiKey != "" {
				return fmt.Errorf("both --server-url and --api-key are required for non-interactive setup\n  Run 'onyx-cli configure' without flags for interactive setup")
			}

			cfg := config.Load()
			onboarding.Run(&cfg)
			return nil
		},
	}

	cmd.Flags().StringVar(&serverURL, "server-url", "", "Onyx server URL (e.g., https://cloud.onyx.app)")
	cmd.Flags().StringVar(&apiKey, "api-key", "", "API key for authentication")

	return cmd
}

func configureNonInteractive(serverURL, apiKey string) error {
	cfg := config.OnyxCliConfig{
		ServerURL:      serverURL,
		APIKey:         apiKey,
		DefaultAgentID: 0,
	}

	// Preserve existing default agent ID if config exists
	if existing := config.Load(); existing.DefaultAgentID != 0 {
		cfg.DefaultAgentID = existing.DefaultAgentID
	}

	// Test connection before saving
	client := api.NewClient(cfg)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	if err := client.TestConnection(ctx); err != nil {
		return fmt.Errorf("connection test failed: %w\n  Check your server URL and API key", err)
	}

	if err := config.Save(cfg); err != nil {
		return fmt.Errorf("could not save config: %w", err)
	}

	fmt.Printf("Config:  %s\n", config.ConfigFilePath())
	fmt.Printf("Server:  %s\n", serverURL)
	fmt.Println("Status:  connected and authenticated")
	return nil
}
