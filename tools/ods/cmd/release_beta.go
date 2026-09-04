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
	Ref       string
	Version   string
	NewBranch bool
	DryRun    bool
	Yes       bool
	Verify    bool
}

// NewReleaseBetaCommand creates the `ods release beta` command.
func NewReleaseBetaCommand() *cobra.Command {
	opts := &ReleaseBetaOptions{}

	cmd := &cobra.Command{
		Use:   "beta",
		Short: "Cut a beta release tag (vX.Y.Z-beta.N) on a new or existing release branch",
		Long: `Cut a beta release tag (vX.Y.Z-beta.N) and push it to origin.

The command asks which branch to cut on:

  - The newest release/vX.Y branch on origin. The base version is one patch
    past the highest stable vX.Y.* tag, so the first beta of a fresh branch is
    vX.Y.0-beta.0 and a beta cut after a stable release previews the next
    patch. N is one past the highest existing counter for the same base,
    starting at 0.
  - A new release/vX.Y+1 branch, one minor past the newest one, created from
    origin/main and tagged vX.Y+1.0-beta.0. --new-branch picks this
    non-interactively.

By default the branch tip is tagged (origin/main for a new branch); --ref
tags an older commit on it. --version pins the base outright and targets its
release branch.

Pushing the tag triggers deployment.yml, which builds the beta images and
moves the "beta" Docker tags.

To validate an existing tag instead of cutting one, see "ods release --check".

Example usage:

    $ ods release beta
    $ ods release beta --new-branch
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
	cmd.Flags().BoolVar(&opts.NewBranch, "new-branch", false, "Cut the first beta on a new release branch one minor past the newest one, instead of asking")
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
	if opts.NewBranch && opts.Version != "" {
		return "", fmt.Errorf("--new-branch derives the base from the new branch, so it cannot be combined with --version")
	}

	newBranch := opts.NewBranch
	// --version names an existing branch, and the non-interactive modes keep
	// their long-standing meaning: cut on the newest release branch.
	if !newBranch && !opts.Yes && !opts.DryRun && opts.Version == "" {
		chosen, err := chooseNewBranch()
		if err != nil {
			return "", err
		}
		newBranch = chosen
	}
	if newBranch {
		return releaseBetaOnNewBranch(opts)
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
		// The prompt can wait a long time, and origin does not reject a beta
		// tag whose base shipped meanwhile (the tag name is new). CI's tag
		// check rejects it, but deployment.yml's image jobs run regardless and
		// would move the "beta" Docker tags backwards. Recompute so the push
		// reflects origin's current state, not the pre-prompt snapshot.
		if err := verifyBetaStateUnchanged(tag, sha, opts); err != nil {
			return "", err
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

// chooseNewBranch asks whether to cut the first beta on a new release branch
// (true) or the next beta on the newest existing one (false).
func chooseNewBranch() (bool, error) {
	version, err := release.NewestReleaseVersion()
	if err != nil {
		return false, fmt.Errorf("failed to detect the newest release branch (pass --version or --new-branch to override): %w", err)
	}
	options := []string{
		fmt.Sprintf("Cut the next beta on the existing release/%s", version),
		fmt.Sprintf("Create release/%s from origin/main and cut its first beta", version.NextMinor()),
	}
	return prompt.Choose("Which release branch should the beta be cut on?", options, 0) == 1, nil
}

// releaseBetaOnNewBranch creates the next minor's release branch from
// origin/main and cuts its first beta on it. It returns the pushed tag name,
// or an empty string when nothing was pushed.
func releaseBetaOnNewBranch(opts *ReleaseBetaOptions) (string, error) {
	log.Info("Fetching main, the release branches, and their tags from origin...")
	branch, tag, sha, err := release.ComputeNewBetaBranch(opts.Ref)
	if err != nil {
		return "", err
	}

	if opts.DryRun {
		log.Warnf("[DRY RUN] Would create %s at %.10s, tag it %s, and push both", branch, sha, tag)
		fmt.Println(tag)
		return "", nil
	}

	if !opts.Yes {
		if !prompt.Confirm(fmt.Sprintf("Create %s at %.10s and tag it %s to trigger the beta build? (Y/n): ", branch, sha, tag)) {
			log.Info("Exiting...")
			return "", nil
		}
		// The prompt can wait a long time; recompute so the push reflects
		// origin's current state, not the pre-prompt snapshot. This also keeps
		// the window in which another cut could create the branch small, which
		// the push itself only guards against for non-fast-forwards.
		freshBranch, freshTag, freshSHA, err := release.ComputeNewBetaBranch(opts.Ref)
		if err != nil {
			return "", err
		}
		if freshBranch != branch || freshTag != tag || freshSHA != sha {
			return "", fmt.Errorf("origin changed while waiting for confirmation: the cut was %s at %.10s tagged %s but is now %s at %.10s tagged %s; re-run to continue", branch, sha, tag, freshBranch, freshSHA, freshTag)
		}
	}

	// The branch goes first: CI's tag check requires the beta's commit to be on
	// origin/<branch>, and deployment.yml runs it as soon as the tag lands.
	if err := git.PushBranch(sha, branch, opts.Verify); err != nil {
		return "", fmt.Errorf("failed to push branch %s: %w", branch, err)
	}
	log.Infof("Created origin/%s at %.10s.", branch, sha)

	if err := git.RunCommand("tag", tag, sha); err != nil {
		return "", fmt.Errorf("failed to create tag %s (origin/%s now exists; re-run without --new-branch): %w", tag, branch, err)
	}
	if err := git.PushTag(tag, false, opts.Verify); err != nil {
		// Roll back the local tag so the command stays retryable. The branch
		// stays: a re-run without --new-branch now targets it and computes the
		// same tag.
		if delErr := git.RunCommand("tag", "-d", tag); delErr != nil {
			log.Warnf("Also failed to delete local tag %s; remove it before retrying: %v", tag, delErr)
		}
		return "", fmt.Errorf("failed to push tag %s (origin/%s now exists; re-run without --new-branch): %w", tag, branch, err)
	}
	log.Infof("Pushed %s; deployment.yml will build the beta images.", tag)
	return tag, nil
}

// verifyBetaStateUnchanged recomputes the beta tag and errors when the answer
// no longer matches the one the user confirmed, which means origin moved
// while the prompt was waiting.
func verifyBetaStateUnchanged(tag, sha string, opts *ReleaseBetaOptions) error {
	freshTag, freshSHA, err := release.ComputeBetaTag(opts.Ref, opts.Version)
	if err != nil {
		return err
	}
	if freshTag != tag || freshSHA != sha {
		return fmt.Errorf("origin changed while waiting for confirmation: the computed tag was %s at %.10s but is now %s at %.10s; re-run to continue", tag, sha, freshTag, freshSHA)
	}
	return nil
}
