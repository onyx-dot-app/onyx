package cmd

import (
	"github.com/spf13/cobra"
)

// NewDevCommand creates the parent dev command for devcontainer operations.
func NewDevCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:     "dev",
		Aliases: []string{"dc"},
		Short:   "Manage the devcontainer",
		Long: `Manage the Onyx devcontainer.

Wraps the devcontainer CLI with workspace-aware defaults.

Commands:
  up        Start the devcontainer
  into      Open a shell inside the running devcontainer
  exec      Run a command inside the devcontainer
  restart   Remove and recreate the devcontainer
  rebuild   Pull the latest image and recreate
  stop      Stop the running devcontainer`,
	}

	cmd.AddCommand(newDevUpCommand())
	cmd.AddCommand(newDevIntoCommand())
	cmd.AddCommand(newDevExecCommand())
	cmd.AddCommand(newDevRestartCommand())
	cmd.AddCommand(newDevRebuildCommand())
	cmd.AddCommand(newDevStopCommand())

	return cmd
}
