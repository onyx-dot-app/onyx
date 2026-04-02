package cmd

import (
	"context"
	"fmt"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/version"
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
)

func newValidateConfigCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "validate-config",
		Short: "Validate configuration and test server connection",
		Example: `  onyx-cli validate-config`,
		RunE: func(cmd *cobra.Command, args []string) error {
			// Check config file
			if !config.ConfigExists() {
				return exitcodes.Newf(exitcodes.NotConfigured, "config file not found at %s\n  Run: onyx-cli configure", config.ConfigFilePath())
			}

			cfg := config.Load()

			// Check API key
			if !cfg.IsConfigured() {
				return exitcodes.New(exitcodes.NotConfigured, "API key is missing\n  Run: onyx-cli configure")
			}

			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Config:  %s\n", config.ConfigFilePath())
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Server:  %s\n", cfg.ServerURL)

			// Test connection
			client := api.NewClient(cfg)
			if err := client.TestConnection(cmd.Context()); err != nil {
				return exitcodes.Newf(exitcodes.Unreachable, "connection failed: %v\n  Reconfigure with: onyx-cli configure", err)
			}

			_, _ = fmt.Fprintln(cmd.OutOrStdout(), "Status:  connected and authenticated")

			// Check backend version compatibility
			vCtx, vCancel := context.WithTimeout(cmd.Context(), 5*time.Second)
			defer vCancel()

			backendVersion, err := client.GetBackendVersion(vCtx)
			if err != nil {
				log.WithError(err).Debug("could not fetch backend version")
			} else if backendVersion == "" {
				log.Debug("server returned empty version string")
			} else {
				_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Version: %s\n", backendVersion)
				min := version.MinServer()
				if sv, ok := version.Parse(backendVersion); ok && sv.LessThan(min) {
					log.Warnf("Server version %s is below minimum required %d.%d, please upgrade",
						backendVersion, min.Major, min.Minor)
				}
			}

			return nil
		},
	}
}
