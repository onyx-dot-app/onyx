package cmd

import (
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/onboarding"
	"github.com/spf13/cobra"
)

func newConfigureCmd(ios *iostreams.IOStreams) *cobra.Command {
	return &cobra.Command{
		Use:   "configure",
		Short: "Configure server URL and personal access token (requires terminal)",
		Long: `Launch the interactive setup wizard to configure the Onyx CLI with your
server URL and personal access token (PAT). The saved config is stored in your
user config directory and is also used by AI agents calling the CLI non-interactively.

To override the config file or skip it entirely, set environment variables:

  export ONYX_SERVER_URL="https://your-onyx-server.com/api"
  export ONYX_PAT="your-pat"`,
		Example: `  onyx-cli configure`,
		RunE: func(cmd *cobra.Command, args []string) error {
			if !ios.IsStdinTTY {
				return exitcodes.New(exitcodes.BadRequest, "configure requires an interactive terminal\n  Use environment variables instead: ONYX_SERVER_URL and ONYX_PAT")
			}
			cfg := config.Load()
			onboarding.Run(&cfg)
			return nil
		},
	}
}
