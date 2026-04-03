package cmd

import (
	"fmt"

	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/spf13/cobra"
)

func newExperimentsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "experiments",
		Short: "List experimental features and their status",
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := config.Load()
			_, _ = fmt.Fprintln(cmd.OutOrStdout(), config.ExperimentsText(cfg.Features))
			return nil
		},
	}
}
