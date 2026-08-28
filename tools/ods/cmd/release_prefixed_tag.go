package cmd

import (
	"fmt"
	"os/exec"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/release"
)

// Some packages are released by pushing a prefixed vX.Y.Z tag that a workflow
// watches, rather than from a release branch. The tag is the version: nothing
// in the tree records it. This is the shared flow for those.

// prefixedTagOptions holds the flags every such release takes.
type prefixedTagOptions struct {
	Bump    string
	Version string
	DryRun  bool
	Yes     bool
	Verify  bool
}

// prefixedTagRelease describes one release target.
type prefixedTagRelease struct {
	// tagPrefix is everything before the version, e.g. "opal/v".
	tagPrefix string
	// tagGlob matches this target's tags for fetching, e.g. "opal/*".
	tagGlob string
	// subject is what the tag publishes, for the confirmation prompt.
	subject string
	// publishes says what happens after the push, for the closing log line.
	publishes string
}

// addFlags registers the shared flags on a release subcommand.
func (r prefixedTagRelease) addFlags(cmd *cobra.Command, opts *prefixedTagOptions) {
	cmd.Flags().StringVar(&opts.Bump, "bump", "patch", "Semver part to bump when --version is unset: patch|minor|major")
	cmd.Flags().StringVar(&opts.Version, "version", "", "Exact version to release (X.Y.Z, no leading v); overrides --bump")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Compute the version but don't tag or push")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip the confirmation prompt")
	cmd.Flags().BoolVar(&opts.Verify, "verify", false, "Run pre-push hooks when pushing the tag; they are skipped by default")
}

// run computes the next version, then tags and pushes it.
func (r prefixedTagRelease) run(opts *prefixedTagOptions) {
	if opts.Version != "" {
		if !release.IsBareVersion(opts.Version) {
			log.Fatalf("--version must be X.Y.Z with no leading v, got %q", opts.Version)
		}
	} else if opts.Bump != "patch" && opts.Bump != "minor" && opts.Bump != "major" {
		log.Fatalf("--bump must be one of patch|minor|major, got %q", opts.Bump)
	}

	// Fetch only this target's tags so the next version is computed against
	// origin's latest release. Targeted + best-effort: a full --tags fetch can
	// exit non-zero just because unrelated local tags would be clobbered, and
	// an offline run should still fall back to local tags.
	log.Infof("Fetching %s tags from origin...", r.tagGlob)
	refspec := fmt.Sprintf("refs/tags/%s:refs/tags/%s", r.tagGlob, r.tagGlob)
	if err := git.RunCommand("fetch", "--quiet", "--force", "origin", refspec); err != nil {
		log.Warnf("Could not fetch %s tags (using local tags): %v", r.tagGlob, err)
	}

	newVersion := opts.Version
	if newVersion == "" {
		current, err := r.latestVersion()
		if err != nil {
			log.Fatalf("Failed to determine the latest version (pass --version): %v", err)
		}
		next, err := bumpSemver(current, opts.Bump)
		if err != nil {
			log.Fatalf("Failed to compute next version: %v", err)
		}
		newVersion = next
		log.Infof("Latest %s release: v%s -> v%s", r.subject, current, newVersion)
	}

	tag := r.tagPrefix + newVersion
	if tagExists(tag) {
		log.Fatalf("Tag %s already exists", tag)
	}

	if opts.DryRun {
		log.Warnf("[DRY RUN] Would tag and push %s", tag)
		return
	}

	if !opts.Yes {
		if !prompt.Confirm(fmt.Sprintf("Tag and push %s to publish %s? (Y/n): ", tag, r.subject)) {
			log.Info("Exiting...")
			return
		}
	}

	if err := git.RunCommand("tag", tag); err != nil {
		log.Fatalf("Failed to create tag %s: %v", tag, err)
	}
	if err := git.PushTag(tag, false, opts.Verify); err != nil {
		// Roll back the local tag so the command stays retryable after a failed push.
		if delErr := git.RunCommand("tag", "-d", tag); delErr != nil {
			log.Warnf("Also failed to delete local tag %s; remove it before retrying: %v", tag, delErr)
		}
		log.Fatalf("Failed to push tag %s: %v", tag, err)
	}
	log.Infof("Pushed %s — %s", tag, r.publishes)
}

// latestVersion returns the highest X.Y.Z among this target's tags.
func (r prefixedTagRelease) latestVersion() (string, error) {
	out, err := exec.Command("git", "tag", "--list", r.tagPrefix+"*", "--sort=-v:refname").Output()
	if err != nil {
		return "", err
	}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		version := strings.TrimPrefix(strings.TrimSpace(line), r.tagPrefix)
		if release.IsBareVersion(version) {
			return version, nil
		}
	}
	return "", fmt.Errorf("no %s* tags found", r.tagPrefix)
}

// bumpSemver increments one segment of an X.Y.Z version, zeroing lower segments.
func bumpSemver(version, part string) (string, error) {
	var major, minor, patch int
	if _, err := fmt.Sscanf(version, "%d.%d.%d", &major, &minor, &patch); err != nil {
		return "", fmt.Errorf("parse %q: %w", version, err)
	}
	switch part {
	case "major":
		return fmt.Sprintf("%d.0.0", major+1), nil
	case "minor":
		return fmt.Sprintf("%d.%d.0", major, minor+1), nil
	default:
		return fmt.Sprintf("%d.%d.%d", major, minor, patch+1), nil
	}
}

// tagExists reports whether the tag is already present locally (tags were just
// fetched from origin, so this also covers origin).
func tagExists(tag string) bool {
	return exec.Command("git", "rev-parse", "-q", "--verify", "refs/tags/"+tag).Run() == nil
}
