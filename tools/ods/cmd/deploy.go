package cmd

import (
	"github.com/spf13/cobra"
)

// NewDeployCommand creates the parent `ods deploy` command. Subcommands hang
// off it (e.g. `ods deploy cloud`) and represent deployment workflows.
func NewDeployCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "deploy",
		Short: "Trigger deployments",
		Long:  "Trigger deployments to Onyx-managed environments.",
	}

	cmd.AddCommand(NewDeployCloudCommand())
	cmd.AddCommand(NewDeployEdgeCommand())
	cmd.AddCommand(NewDeployWikiCommand())

	return cmd
}
