package cmd

import (
	"fmt"
	"os/exec"
	"regexp"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
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
	if opts.Version != "" && !bareSemverRe.MatchString(opts.Version) {
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
	if err := fetchCloudTags(); err != nil {
		log.Warnf("Could not fetch cloud tags (using local tags): %v", err)
	}

	sha, err := resolveCommit(opts.Ref)
	if err != nil {
		return err
	}

	tag, err := computeCloudTag(sha, opts.Version)
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

// computeCloudTag returns the next cloud tag for commitSHA. The base version is
// "v" + overrideVersion when given, else one minor past the newest release
// branch on origin that does not contain the commit; the counter is one past
// the highest existing "-cloud.N" tag for that base.
func computeCloudTag(commitSHA, overrideVersion string) (string, error) {
	// The ancestry checks below cannot be answered truthfully in a shallow
	// clone; fail loudly instead.
	shallow, err := git.IsShallowRepository()
	if err != nil {
		return "", err
	}
	if shallow {
		return "", fmt.Errorf("this is a shallow clone, so cloud tag computation cannot check branch ancestry")
	}

	onMain, err := git.IsAncestor(commitSHA, "origin/main")
	if err != nil {
		return "", err
	}
	if !onMain {
		return "", fmt.Errorf("commit %s is not on origin/main; cloud releases are cut from main", commitSHA)
	}

	var base string
	if overrideVersion != "" {
		base = "v" + overrideVersion
	} else {
		branchVersion, err := findTargetReleaseVersion(commitSHA)
		if err != nil {
			return "", fmt.Errorf("failed to detect the base version from release branches (pass --version to override): %w", err)
		}
		base = branchVersion.nextMinorBase()
		log.Infof("Newest release branch not containing %.10s: release/%s -> cloud base %s", commitSHA, branchVersion, base)
	}

	return nextCloudTag(base)
}

// fetchCloudTags force-updates the local v*-cloud.* tags from origin. A fetch
// refspec allows only one wildcard per side, so the matching tag names are
// listed with ls-remote (which globs freely) and fetched by exact refspec.
func fetchCloudTags() error {
	out, err := exec.Command("git", "ls-remote", "--tags", "origin", "v*-cloud.*").Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok && len(exitErr.Stderr) > 0 {
			return fmt.Errorf("git ls-remote failed: %w: %s", err, strings.TrimSpace(string(exitErr.Stderr)))
		}
		return fmt.Errorf("git ls-remote failed: %w", err)
	}

	refspecs := []string{}
	for _, line := range strings.Split(string(out), "\n") {
		// Each line is "<sha>\trefs/tags/<name>".
		_, ref, found := strings.Cut(line, "\t")
		if !found {
			continue
		}
		ref = strings.TrimSpace(ref)
		// Annotated tags list a second, peeled "<ref>^{}" entry; the plain ref
		// covers it.
		if strings.HasSuffix(ref, "^{}") {
			continue
		}
		refspecs = append(refspecs, fmt.Sprintf("+%s:%s", ref, ref))
	}
	if len(refspecs) == 0 {
		return nil
	}

	args := append([]string{"fetch", "--quiet", "origin"}, refspecs...)
	return git.RunCommand(args...)
}

// nextCloudTag returns base + "-cloud.N" where N is one past the highest
// existing counter for base among local tags (fetched from origin beforehand),
// or 0 when none exist. Counters compare numerically: lexically "-cloud.9" >
// "-cloud.10", which would compute a colliding tag. Tags of other bases and
// tags whose suffix is not a plain integer are ignored.
func nextCloudTag(base string) (string, error) {
	out, err := exec.Command("git", "tag", "--list", base+"-cloud.*").Output()
	if err != nil {
		return "", fmt.Errorf("git tag --list failed: %w", err)
	}
	counterRe := regexp.MustCompile(`^` + regexp.QuoteMeta(base) + `-cloud\.(\d+)$`)
	next := 0
	for _, line := range strings.Split(string(out), "\n") {
		matches := counterRe.FindStringSubmatch(strings.TrimSpace(line))
		if matches == nil {
			continue
		}
		n, err := strconv.Atoi(matches[1])
		if err != nil {
			continue
		}
		if n >= next {
			next = n + 1
		}
	}
	return fmt.Sprintf("%s-cloud.%d", base, next), nil
}

// resolveCommit resolves a commit-ish to a full commit SHA.
func resolveCommit(ref string) (string, error) {
	out, err := exec.Command("git", "rev-parse", "--verify", ref+"^{commit}").Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok && len(exitErr.Stderr) > 0 {
			return "", fmt.Errorf("failed to resolve %q: %w: %s", ref, err, strings.TrimSpace(string(exitErr.Stderr)))
		}
		return "", fmt.Errorf("failed to resolve %q: %w", ref, err)
	}
	return strings.TrimSpace(string(out)), nil
}
