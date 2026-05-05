package cmd

import (
	"github.com/spf13/cobra"
)

// NewDeployCommand creates the parent `ods deploy` command. Subcommands hang
// off it (e.g. `ods deploy edge`) and represent ad-hoc deployment workflows.
func NewDeployCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "deploy",
		Short: "Trigger ad-hoc deployments",
		Long:  "Trigger ad-hoc deployments to Onyx-managed environments.",
	}

	cmd.AddCommand(NewDeployEdgeCommand())

	return cmd
}
