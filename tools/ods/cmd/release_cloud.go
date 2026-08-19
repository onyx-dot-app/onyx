package cmd

import (
	"fmt"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/release"
)

// ReleaseCloudOptions holds options for the release cloud command.
type ReleaseCloudOptions struct {
	Ref     string
	Version string
	DryRun  bool
	Yes     bool
	Verify  bool
}

// NewReleaseCloudCommand creates the `ods release cloud` command.
func NewReleaseCloudCommand() *cobra.Command {
	opts := &ReleaseCloudOptions{}

	cmd := &cobra.Command{
		Use:   "cloud",
		Short: "Cut the next cloud release tag (vX.Y.0-cloud.N) off main",
		Long: `Cut the next cloud release tag (vX.Y.0-cloud.N) and push it to origin.

The base version is one minor past the newest release/vX.Y branch that does
not contain the tagged commit.
A commit on main after the release/v4.6 cut is therefore tagged
v4.7.0-cloud.N, never v4.6.0-cloud.N, so cloud tags order correctly against
stable and beta tags under semver. N is one past the highest existing counter
for the same base, starting at 0.

Pushing the tag triggers deployment.yml, which builds the cloud images.

To validate an existing tag instead of cutting one, see "ods release --check".

Example usage:

    $ ods release cloud
    $ ods release cloud --dry-run
    $ ods release cloud --ref 1a2b3c4d
    $ ods release cloud --version 5.0.0`,
		Args:         cobra.NoArgs,
		SilenceUsage: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			return releaseCloud(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Ref, "ref", "origin/main", "Commit-ish to tag; must be on origin/main")
	cmd.Flags().StringVar(&opts.Version, "version", "", "Base version override (X.Y.Z, no leading v); skips release-branch detection")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Compute and print the tag but don't tag or push")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip the confirmation prompt")
	cmd.Flags().BoolVar(&opts.Verify, "verify", false, "Run pre-push hooks when pushing the tag; they are skipped by default")

	return cmd
}

func releaseCloud(opts *ReleaseCloudOptions) error {
	if opts.Version != "" && !release.IsBareVersion(opts.Version) {
		return fmt.Errorf("--version must be X.Y.Z with no leading v, got %q", opts.Version)
	}

	// Deployment tags must be cut against origin's current state.
	log.Info("Fetching main and cloud tags from origin...")
	if err := git.RunCommand("fetch", "--quiet", "--force", "origin", "+refs/heads/main:refs/remotes/origin/main"); err != nil {
		return fmt.Errorf("failed to fetch origin/main: %w", err)
	}
	// Best-effort: a failure here only leaves the counter stale, which is safe.
	// If the computed tag already exists on origin, the push (which is never
	// forced) is rejected and rolled back.
	if err := release.FetchTags("v*-cloud.*"); err != nil {
		log.Warnf("Could not fetch cloud tags (using local tags): %v", err)
	}

	sha, err := release.ResolveCommit(opts.Ref)
	if err != nil {
		return err
	}

	tag, err := release.ComputeCloudTag(sha, opts.Version)
	if err != nil {
		return err
	}

	if opts.DryRun {
		log.Warnf("[DRY RUN] Would tag %.10s as %s and push", sha, tag)
		fmt.Println(tag)
		return nil
	}

	if !opts.Yes {
		if !prompt.Confirm(fmt.Sprintf("Tag %.10s as %s and push to trigger the cloud build? (Y/n): ", sha, tag)) {
			log.Info("Exiting...")
			return nil
		}
	}

	if err := git.RunCommand("tag", tag, sha); err != nil {
		return fmt.Errorf("failed to create tag %s: %w", tag, err)
	}
	if err := git.PushTag(tag, false, opts.Verify); err != nil {
		// Roll back the local tag so the command stays retryable after a failed
		// push.
		if delErr := git.RunCommand("tag", "-d", tag); delErr != nil {
			log.Warnf("Also failed to delete local tag %s; remove it before retrying: %v", tag, delErr)
		}
		return fmt.Errorf("failed to push tag %s: %w", tag, err)
	}
	log.Infof("Pushed %s; deployment.yml will build the cloud images.", tag)
	return nil
}
