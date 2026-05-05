package cmd

import (
	"github.com/spf13/cobra"
)

func newDevRestartCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "restart",
		Short: "Remove and recreate the devcontainer",
		Long: `Remove the existing devcontainer and recreate it.

Uses the cached image — for a full image rebuild, use "ods dev rebuild".

Examples:
  ods dev restart`,
		Run: func(cmd *cobra.Command, args []string) {
			runDevcontainer("up", []string{"--remove-existing-container"})
		},
	}

	return cmd
}
