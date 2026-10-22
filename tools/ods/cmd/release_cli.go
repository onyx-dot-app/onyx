package cmd

import (
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
)

var cliRelease = prefixedTagRelease{
	tagPrefix: "cli/v",
	tagGlob:   "cli/*",
	subject:   "onyx-cli",
	publishes: "release-cli.yml will build and publish to PyPI, and create the GitHub release.",
}

// NewReleaseCLICommand creates the `ods release cli` command.
func NewReleaseCLICommand() *cobra.Command {
	opts := &prefixedTagOptions{}

	cmd := &cobra.Command{
		Use:   "cli",
		Short: "Cut a new onyx-cli release by pushing a cli/vX.Y.Z tag",
		Long: `Cut a new onyx-cli release by pushing a cli/vX.Y.Z tag.

The cli/v* tags are the source of truth for the version — nothing in cli/ records
it. cli/internal/_version.py reads the tag at build time, and the build stamps it
into the Go binary. This command reads the latest cli/v* tag, computes the next
version, and pushes the new tag to origin.

release-cli.yml then builds a wheel for every platform, publishes them to PyPI,
and creates the GitHub release with the standalone archives.

By default the patch version is bumped. Use --bump minor|major, or pin an exact
--version.

Example usage:

    $ ods release cli
    $ ods release cli --bump minor
    $ ods release cli --version 1.5.0
    $ ods release cli --dry-run`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			if err := cliRelease.run(opts); err != nil {
				log.Fatal(err)
			}
		},
	}

	cliRelease.addFlags(cmd, opts)

	return cmd
}
