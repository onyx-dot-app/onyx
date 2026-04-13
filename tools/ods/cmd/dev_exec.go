package cmd

import (
	"github.com/spf13/cobra"
)

func newDevExecCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "exec [--] <command> [args...]",
		Short: "Run a command inside the devcontainer",
		Long: `Run an arbitrary command inside the running devcontainer.
All arguments are treated as positional (flags like -it are passed through).

Examples:
  ods dev exec npm test
  ods dev exec -- ls -la
  ods dev exec -it echo hello`,
		Args:               cobra.MinimumNArgs(1),
		DisableFlagParsing: true,
		Run: func(cmd *cobra.Command, args []string) {
			if len(args) > 0 && args[0] == "--" {
				args = args[1:]
			}
			runDevExec(args)
		},
	}

	return cmd
}
