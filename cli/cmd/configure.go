package cmd

import (
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/onboarding"
	"github.com/spf13/cobra"
)

func newConfigureCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "configure",
		Short: "Configure server URL and API key (requires terminal)",
		Long: `Launch the interactive setup wizard to configure the Onyx CLI with your
server URL and API key. The saved config is shared with all CLI users on this
machine, including AI agents calling the CLI non-interactively.

To override the config file or skip it entirely, set environment variables:

  export ONYX_SERVER_URL="https://your-onyx-server.com"
  export ONYX_API_KEY="your-api-key"`,
		Example: `  onyx-cli configure`,
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := config.Load()
			onboarding.Run(&cfg)
			return nil
		},
	}
}
