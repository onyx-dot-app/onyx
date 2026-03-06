package cmd

import (
	"fmt"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/spf13/cobra"
)

func newValidateConfigCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "validate-config",
		Short: "Validate configuration and test server connection",
		RunE: func(cmd *cobra.Command, args []string) error {
			// Check config file
			if !config.ConfigExists() {
				return fmt.Errorf("config file not found at %s\n  Run 'onyx-cli configure' to set up", config.ConfigFilePath())
			}

			cfg := config.Load()

			// Check API key
			if !cfg.IsConfigured() {
				return fmt.Errorf("API key is missing\n  Run 'onyx-cli configure' to set up")
			}

			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Config:  %s\n", config.ConfigFilePath())
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Server:  %s\n", cfg.ServerURL)

			// Test connection
			client := api.NewClient(cfg)
			if err := client.TestConnection(cmd.Context()); err != nil {
				return fmt.Errorf("connection failed: %w", err)
			}

			_, _ = fmt.Fprintln(cmd.OutOrStdout(), "Status:  connected and authenticated")
			return nil
		},
	}
}
