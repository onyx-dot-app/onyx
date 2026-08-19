package cmd

import (
	"regexp"

	"github.com/spf13/cobra"
)

// bareSemverRe matches a bare X.Y.Z version (no leading v). Leading zeroes are
// rejected per SemVer 2.0.0 item 2.
var bareSemverRe = regexp.MustCompile(`^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$`)

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

  - A cloud tag (vX.Y.Z-cloud.N) must be the tag "ods release cloud" would
    have computed: its commit is on origin/main, its base matches the release
    branches, and its counter is one past the previous counter for that base.
  - A stable tag (vX.Y.Z) must sit on origin/release/vX.Y, its patch must be
    one past the highest existing vX.Y.* patch, and its predecessor must be an
    ancestor of the tagged commit.

deployment.yml runs this against pushed release tags before building. --ref
may name the tag directly; otherwise the single release tag pointing at --ref
(default HEAD) is checked.

Example usage:

    $ ods release --check
    $ ods release --check --ref v4.7.0-cloud.3
    $ ods release --check --ref v4.6.2`,
		Args:         cobra.NoArgs,
		SilenceUsage: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			if !check {
				return cmd.Help()
			}
			return checkReleaseTag(ref)
		},
	}

	cmd.Flags().BoolVar(&check, "check", false, "Validate an existing release tag (named by --ref, or pointing at it) instead of cutting one")
	cmd.Flags().StringVar(&ref, "ref", "HEAD", "Tag to check, or a commit-ish that a single release tag points at")

	cmd.AddCommand(NewReleaseOpalCommand())
	cmd.AddCommand(NewReleaseCloudCommand())

	return cmd
}
