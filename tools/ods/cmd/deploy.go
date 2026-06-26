package cmd

import (
	"github.com/spf13/cobra"
)

// deployNoVerify, when set, skips git pre-push hooks (passes --no-verify to
// git push) for deploy subcommands that push to git. It is bound to the
// persistent --no-verify flag on the parent `deploy` command and inherited by
// all subcommands; subcommands that don't push to git ignore it.
var deployNoVerify bool

// NewDeployCommand creates the parent `ods deploy` command. Subcommands hang
// off it (e.g. `ods deploy edge`) and represent ad-hoc deployment workflows.
func NewDeployCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "deploy",
		Short: "Trigger ad-hoc deployments",
		Long:  "Trigger ad-hoc deployments to Onyx-managed environments.",
	}

	cmd.PersistentFlags().BoolVar(&deployNoVerify, "no-verify", false, "Skip git pre-push hooks (pass --no-verify to git push) when a deploy pushes to git")

	cmd.AddCommand(NewDeployEdgeCommand())
	cmd.AddCommand(NewDeployWikiCommand())

	return cmd
}
