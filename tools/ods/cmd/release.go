package cmd

import (
	"github.com/spf13/cobra"
)

// NewReleaseCommand creates the parent `ods release` command. Subcommands hang
// off it (e.g. `ods release opal`) and cut releases of Onyx-published packages.
func NewReleaseCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "release",
		Short: "Cut releases of Onyx-published packages",
		Long:  "Cut releases of Onyx-published packages.",
	}

	cmd.AddCommand(NewReleaseOpalCommand())

	return cmd
}
