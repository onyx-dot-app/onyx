package cmd

import (
	"regexp"

	"github.com/spf13/cobra"
)

// bareSemverRe matches a bare X.Y.Z version (no leading v). Leading zeroes are
// rejected per SemVer 2.0.0 item 2.
var bareSemverRe = regexp.MustCompile(`^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$`)

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
