package cmd

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/release"
)

// NewReleaseCommand creates the parent `ods release` command. Subcommands hang
// off it (e.g. `ods release opal`) and cut releases of Onyx-published
// packages; --check validates an existing release tag instead.
func NewReleaseCommand() *cobra.Command {
	var check bool
	var ref string

	cmd := &cobra.Command{
		Use:   "release",
		Short: "Cut releases of Onyx-published packages",
		Long: `Cut releases of Onyx-published packages.

With --check, no tag is cut. Instead the command validates an existing release
tag:

  - A cloud tag (vX.Y.Z-cloud.N) must be the tag "ods deploy cloud" would
    have computed: its commit is on origin/main, its base matches the release
    branches, and its counter is one past the previous counter for that base.
  - A stable tag (vX.Y.Z) must sit on origin/release/vX.Y, its patch must be
    one past the highest existing vX.Y.* patch, and its predecessor must be an
    ancestor of the tagged commit.
  - A beta tag (vX.Y.Z-beta.N) must sit on origin/release/vX.Y, its base must
    not have shipped as a stable tag yet, its counter must be one past the
    previous counter for that base, and its predecessor must be an ancestor of
    the tagged commit.

deployment.yml runs this against pushed release tags before building. --ref
may name the tag directly; otherwise the single release tag pointing at --ref
(default HEAD) is checked.

Example usage:

    $ ods release --check
    $ ods release --check --ref v4.7.0-cloud.3
    $ ods release --check --ref v4.6.2
    $ ods release --check --ref v4.7.0-beta.1`,
		Args:         cobra.NoArgs,
		SilenceUsage: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			if !check {
				// A lone --ref would otherwise print help and exit 0, hiding
				// a mistyped check invocation from CI.
				if cmd.Flags().Changed("ref") {
					return fmt.Errorf("--ref requires --check")
				}
				return cmd.Help()
			}
			return release.CheckTag(ref)
		},
	}

	cmd.Flags().BoolVar(&check, "check", false, "Validate an existing release tag (named by --ref, or pointing at it) instead of cutting one")
	cmd.Flags().StringVar(&ref, "ref", "HEAD", "Tag to check, or a commit-ish that a single release tag points at")

	cmd.AddCommand(NewReleaseOpalCommand())
	cmd.AddCommand(NewReleaseTFProviderCommand())

	return cmd
}
