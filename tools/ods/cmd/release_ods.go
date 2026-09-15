package cmd

import (
	"github.com/spf13/cobra"
)

var odsRelease = prefixedTagRelease{
	tagPrefix: "ods/v",
	tagGlob:   "ods/*",
	subject:   "onyx-devtools",
	publishes: "release-devtools.yml will build and publish to PyPI, then open the pin upgrade PR.",
}

// NewReleaseODSCommand creates the `ods release ods` command.
func NewReleaseODSCommand() *cobra.Command {
	opts := &prefixedTagOptions{}

	cmd := &cobra.Command{
		Use:   "ods",
		Short: "Cut a new onyx-devtools release by pushing an ods/vX.Y.Z tag",
		Long: `Cut a new onyx-devtools release by pushing an ods/vX.Y.Z tag.

The ods/v* tags are the source of truth for the version — nothing in tools/ods
records it. tools/ods/internal/_version.py reads the tag at build time, and the
build stamps it into the Go binary. This command reads the latest ods/v* tag,
computes the next version, and pushes the new tag to origin.

release-devtools.yml then builds a wheel of onyx-devtools and onyx-devtools-audit
for every platform and publishes both to PyPI under this version. It also opens a
PR that moves every onyx-devtools== pin to the new version, so the repo picks the
release up without a second command.

By default the patch version is bumped. Use --bump minor|major, or pin an exact
--version.

Example usage:

    $ ods release ods
    $ ods release ods --bump minor
    $ ods release ods --version 0.14.0
    $ ods release ods --dry-run`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			odsRelease.run(opts)
		},
	}

	odsRelease.addFlags(cmd, opts)

	return cmd
}
