package cmd

import (
	"github.com/spf13/cobra"
)

var opalRelease = prefixedTagRelease{
	tagPrefix: "opal/v",
	tagGlob:   "opal/*",
	subject:   "@onyx-ai/opal",
	publishes: "release-opal.yml will build and publish to npm.",
}

// NewReleaseOpalCommand creates the `ods release opal` command.
func NewReleaseOpalCommand() *cobra.Command {
	opts := &prefixedTagOptions{}

	cmd := &cobra.Command{
		Use:   "opal",
		Short: "Cut a new @onyx-ai/opal release by pushing an opal/vX.Y.Z tag",
		Long: `Cut a new @onyx-ai/opal release by pushing an opal/vX.Y.Z tag.

The opal/v* tags are the source of truth for the version — web/lib/opal/package.json
stays at 0.0.0 and release-opal.yml sets the published version from the tag. This
command reads the latest opal/v* tag, computes the next version, and pushes the new
tag to origin; release-opal.yml then builds and publishes to npm.

By default the patch version is bumped. Use --bump minor|major, or pin an exact
--version.

Example usage:

    $ ods release opal
    $ ods release opal --bump minor
    $ ods release opal --version 0.2.0`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			opalRelease.run(opts)
		},
	}

	opalRelease.addFlags(cmd, opts)

	return cmd
}
