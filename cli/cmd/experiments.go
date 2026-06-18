package cmd

import (
	"fmt"

	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/spf13/cobra"
)

func newExperimentsCmd(ios *iostreams.IOStreams) *cobra.Command {
	return &cobra.Command{
		Use:   "experiments",
		Short: "List experimental features and their status",
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := config.Load()
			fmt.Fprintln(ios.Out, config.ExperimentsText(cfg.Features))
			return nil
		},
	}
}
