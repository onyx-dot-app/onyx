package cmd

import (
	"fmt"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/release"
)

// ReleaseBetaOptions holds options for the release beta command.
type ReleaseBetaOptions struct {
	Ref     string
	Version string
	DryRun  bool
	Yes     bool
	Verify  bool
}

// NewReleaseBetaCommand creates the `ods release beta` command.
func NewReleaseBetaCommand() *cobra.Command {
	opts := &ReleaseBetaOptions{}

	cmd := &cobra.Command{
		Use:   "beta",
		Short: "Cut the next beta release tag (vX.Y.Z-beta.N) on a release branch",
		Long: `Cut the next beta release tag (vX.Y.Z-beta.N) and push it to origin.

The target branch is the newest release/vX.Y branch on origin. The base
version is one patch past the highest stable vX.Y.* tag, so the first beta
of a fresh branch is vX.Y.0-beta.0 and a beta cut after a stable release
previews the next patch. N is one past the highest existing counter for the
same base, starting at 0.

By default the branch tip is tagged; --ref tags an older commit on the
branch. --version pins the base outright and targets its release branch.

Pushing the tag triggers deployment.yml, which builds the beta images and
moves the "beta" Docker tags.

To validate an existing tag instead of cutting one, see "ods release --check".

Example usage:

    $ ods release beta
    $ ods release beta --dry-run
    $ ods release beta --ref 1a2b3c4d
    $ ods release beta --version 4.7.0`,
		Args:         cobra.NoArgs,
		SilenceUsage: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			tag, err := releaseBeta(opts)
			if err != nil || tag == "" {
				return err
			}
			announceDeploymentRun(tag)
			return nil
		},
	}

	cmd.Flags().StringVar(&opts.Ref, "ref", "", "Commit-ish to tag; must be on the target release branch (default: its tip)")
	cmd.Flags().StringVar(&opts.Version, "version", "", "Base version override (X.Y.Z, no leading v); skips branch and patch detection")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Compute and print the tag but don't tag or push")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip the confirmation prompt")
	cmd.Flags().BoolVar(&opts.Verify, "verify", false, "Run pre-push hooks when pushing the tag; they are skipped by default")

	return cmd
}

// releaseBeta computes and pushes the next beta tag. It returns the pushed
// tag name, or an empty string when nothing was pushed (dry run, declined
// prompt, or any failure).
func releaseBeta(opts *ReleaseBetaOptions) (string, error) {
	if opts.Version != "" && !release.IsBareVersion(opts.Version) {
		return "", fmt.Errorf("--version must be X.Y.Z with no leading v, got %q", opts.Version)
	}

	log.Info("Fetching the release branch and its tags from origin...")
	tag, sha, err := release.ComputeBetaTag(opts.Ref, opts.Version)
	if err != nil {
		return "", err
	}

	if opts.DryRun {
		log.Warnf("[DRY RUN] Would tag %.10s as %s and push", sha, tag)
		fmt.Println(tag)
		return "", nil
	}

	if !opts.Yes {
		if !prompt.Confirm(fmt.Sprintf("Tag %.10s as %s and push to trigger the beta build? (Y/n): ", sha, tag)) {
			log.Info("Exiting...")
			return "", nil
		}
	}

	if err := git.RunCommand("tag", tag, sha); err != nil {
		return "", fmt.Errorf("failed to create tag %s: %w", tag, err)
	}
	if err := git.PushTag(tag, false, opts.Verify); err != nil {
		// Roll back the local tag so the command stays retryable after a failed
		// push.
		if delErr := git.RunCommand("tag", "-d", tag); delErr != nil {
			log.Warnf("Also failed to delete local tag %s; remove it before retrying: %v", tag, delErr)
		}
		return "", fmt.Errorf("failed to push tag %s: %w", tag, err)
	}
	log.Infof("Pushed %s; deployment.yml will build the beta images.", tag)
	return tag, nil
}
