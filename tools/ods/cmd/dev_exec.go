package cmd

import (
	"github.com/spf13/cobra"
)

func newDevExecCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "exec -- <command> [args...]",
		Short: "Run a command inside the devcontainer",
		Long: `Run an arbitrary command inside the running devcontainer.

Examples:
  ods dev exec -- ls -la
  ods dev exec -- npm test`,
		Args:               cobra.MinimumNArgs(1),
		DisableFlagParsing: true,
		Run: func(cmd *cobra.Command, args []string) {
			runDevExec(args)
		},
	}

	return cmd
}
