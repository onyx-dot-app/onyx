package cmd

import (
	"context"
	"fmt"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/version"
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
)

func newValidateConfigCmd(ios *iostreams.IOStreams) *cobra.Command {
	return &cobra.Command{
		Use:   "validate-config",
		Short: "Check CLI configuration and server connectivity",
		Long: `Check that the CLI is configured, the server is reachable, and the personal
access token (PAT) is valid. Also reports the server version and warns if it
is below the minimum required.`,
		Example: `  onyx-cli validate-config`,
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg, err := requireConfig()
			if err != nil {
				return err
			}

			if config.ConfigExists() {
				fmt.Fprintf(ios.Out, "Config:  %s\n", config.ConfigFilePath())
			} else {
				fmt.Fprintln(ios.Out, "Config:  environment variables")
			}
			fmt.Fprintf(ios.Out, "Server:  %s\n", cfg.ServerURL)

			// Test connection
			client := api.NewClient(cfg)
			if err := client.TestConnection(cmd.Context()); err != nil {
				return apiErrorToExit(err, "connection check failed")
			}

			fmt.Fprintln(ios.Out, "Status:  connected and authenticated")

			// Check backend version compatibility
			vCtx, vCancel := context.WithTimeout(cmd.Context(), 5*time.Second)
			defer vCancel()

			backendVersion, err := client.GetBackendVersion(vCtx)
			switch {
			case err != nil:
				log.WithError(err).Debug("could not fetch backend version")
			case backendVersion == "":
				log.Debug("server returned empty version string")
			default:
				fmt.Fprintf(ios.Out, "Version: %s\n", backendVersion)
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
