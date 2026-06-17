package cmd

import (
	"fmt"
	"os/exec"
	"regexp"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

const opalTagPrefix = "opal/v"

// opalSemverRe matches a bare X.Y.Z version (no leading v).
var opalSemverRe = regexp.MustCompile(`^\d+\.\d+\.\d+$`)

// ReleaseOpalOptions holds options for the release opal command.
type ReleaseOpalOptions struct {
	Bump    string
	Version string
	DryRun  bool
	Yes     bool
}

// NewReleaseOpalCommand creates the `ods release opal` command.
func NewReleaseOpalCommand() *cobra.Command {
	opts := &ReleaseOpalOptions{}

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
			releaseOpal(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Bump, "bump", "patch", "Semver part to bump when --version is unset: patch|minor|major")
	cmd.Flags().StringVar(&opts.Version, "version", "", "Exact version to release (X.Y.Z, no leading v); overrides --bump")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Compute the version but don't tag or push")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip the confirmation prompt")

	return cmd
}

func releaseOpal(opts *ReleaseOpalOptions) {
	if opts.Version != "" {
		if !opalSemverRe.MatchString(opts.Version) {
			log.Fatalf("--version must be X.Y.Z with no leading v, got %q", opts.Version)
		}
	} else if opts.Bump != "patch" && opts.Bump != "minor" && opts.Bump != "major" {
		log.Fatalf("--bump must be one of patch|minor|major, got %q", opts.Bump)
	}

	// Fetch only opal/* tags so the next version is computed against origin's
	// latest release. Targeted + best-effort: a full --tags fetch can exit
	// non-zero just because unrelated local tags would be clobbered, and an
	// offline run should still fall back to local tags.
	log.Info("Fetching opal tags from origin...")
	if err := git.RunCommand("fetch", "--quiet", "--force", "origin", "refs/tags/opal/*:refs/tags/opal/*"); err != nil {
		log.Warnf("Could not fetch opal tags (using local tags): %v", err)
	}

	newVersion := opts.Version
	if newVersion == "" {
		current, err := latestOpalVersion()
		if err != nil {
			log.Fatalf("Failed to determine latest opal version (pass --version): %v", err)
		}
		next, err := bumpSemver(current, opts.Bump)
		if err != nil {
			log.Fatalf("Failed to compute next version: %v", err)
		}
		newVersion = next
		log.Infof("Latest opal release: v%s -> v%s", current, newVersion)
	}

	tag := opalTagPrefix + newVersion
	if opalTagExists(tag) {
		log.Fatalf("Tag %s already exists", tag)
	}

	if opts.DryRun {
		log.Warnf("[DRY RUN] Would tag and push %s", tag)
		return
	}

	if !opts.Yes {
		if !prompt.Confirm(fmt.Sprintf("Tag and push %s to publish @onyx-ai/opal? (Y/n): ", tag)) {
			log.Info("Exiting...")
			return
		}
	}

	if err := git.RunCommand("tag", tag); err != nil {
		log.Fatalf("Failed to create tag %s: %v", tag, err)
	}
	if err := git.RunCommand("push", "origin", tag); err != nil {
		// Roll back the local tag so the command stays retryable after a failed push.
		if delErr := git.RunCommand("tag", "-d", tag); delErr != nil {
			log.Warnf("Also failed to delete local tag %s; remove it before retrying: %v", tag, delErr)
		}
		log.Fatalf("Failed to push tag %s: %v", tag, err)
	}
	log.Infof("Pushed %s — release-opal.yml will build and publish to npm.", tag)
}

// latestOpalVersion returns the highest X.Y.Z among the opal/v* tags.
func latestOpalVersion() (string, error) {
	out, err := exec.Command("git", "tag", "--list", opalTagPrefix+"*", "--sort=-v:refname").Output()
	if err != nil {
		return "", err
	}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		version := strings.TrimPrefix(strings.TrimSpace(line), opalTagPrefix)
		if opalSemverRe.MatchString(version) {
			return version, nil
		}
	}
	return "", fmt.Errorf("no %s* tags found", opalTagPrefix)
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

// opalTagExists reports whether the tag is already present locally (tags were
// just fetched from origin, so this also covers origin).
func opalTagExists(tag string) bool {
	return exec.Command("git", "rev-parse", "-q", "--verify", "refs/tags/"+tag).Run() == nil
}
