package cmd

import (
	"regexp"

	"github.com/spf13/cobra"
)

// bareSemverRe matches a bare X.Y.Z version (no leading v).
var bareSemverRe = regexp.MustCompile(`^\d+\.\d+\.\d+$`)

// NewReleaseCommand creates the parent `ods release` command. Subcommands hang
// off it (e.g. `ods release opal`) and cut releases of Onyx-published packages.
func NewReleaseCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "release",
		Short: "Cut releases of Onyx-published packages",
		Long:  "Cut releases of Onyx-published packages.",
	}

	cmd.AddCommand(NewReleaseOpalCommand())
	cmd.AddCommand(NewReleaseCloudCommand())

	return cmd
}
