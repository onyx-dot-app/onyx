package cmd

import (
	"fmt"
	"os/exec"
	"regexp"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/config"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/release"
)

const (
	edgeTagName = "edge"

	// Deploys are much shorter than the builds they follow.
	deployPollTimeout = 30 * time.Minute

	// devBuildSlugMaxLen keeps derived tags well under Docker's 128-character
	// tag limit once the prefix, short SHA and -dev suffix are added.
	devBuildSlugMaxLen = 40
)

var (
	devBuildSlugInvalidRe = regexp.MustCompile(`[^a-z0-9-]+`)
	devBuildSlugDashesRe  = regexp.MustCompile(`-{2,}`)
	fullCommitSHARe       = regexp.MustCompile(`^[0-9a-f]{40}$`)
	// dockerTagRe is Docker's tag grammar with room for the -dev suffix that
	// deployment.yml appends.
	dockerTagRe = regexp.MustCompile(`^[A-Za-z0-9_][A-Za-z0-9_.-]{0,123}$`)
)

// DeployEdgeOptions holds options for the deploy edge command.
type DeployEdgeOptions struct {
	Ref            string
	Tag            string
	TargetRepo     string
	TargetWorkflow string
	DryRun         bool
	Yes            bool
	NoWaitDeploy   bool
	Verify         bool
}

// NewDeployEdgeCommand creates the `ods deploy edge` command.
func NewDeployEdgeCommand() *cobra.Command {
	opts := &DeployEdgeOptions{}

	cmd := &cobra.Command{
		Use:   "edge",
		Short: "Build edge images off main or a branch and deploy to the configured target",
		Long: `Build images off origin/main or a pushed branch, then dispatch the configured deploy workflow.

Without --ref, or with --ref main, this command will:
  1. Force-push the 'edge' tag to origin/main, triggering the build
  2. Wait for the build workflow to finish
  3. Dispatch the configured deploy workflow with version_tag=edge
  4. Wait for the deploy workflow to finish

With --ref <branch or commit>, this command will:
  1. Resolve the ref to a commit on origin (push it first)
  2. Push the tag dev-build-<branch>-<short-sha> on that commit, triggering the build
     (pass --tag to choose the name; it must start with dev-build-)
  3. Wait for the build workflow to finish
  4. Dispatch the configured deploy workflow with version_tag=<tag>
  5. Wait for the deploy workflow to finish

A dev-build tag never moves. If it already points at the commit, the command
waits for that tag's build and does not push again. If it points at another
commit, the command stops.

Branch deploys have these requirements and side effects:
  - The onyx repo's "release" environment must admit tags that match
    dev-build-* (Settings > Environments > release > Deployment branches and
    tags). Without this rule GitHub rejects the build jobs.
  - The images are published to Docker Hub, which is public.
  - The scheduled nightly deploy replaces a branch deployment.

All GitHub operations run through the gh CLI, so authorization is enforced
by your gh credentials and GitHub's repo/workflow permissions.

On first run, you'll be prompted for the deploy target repo and workflow
filename, saved to the ods config file (~/.config/onyx-dev/config.json on
Linux/macOS) and reused on subsequent runs. The target repo is shared across
all deploy subcommands; the workflow filename is per-subcommand. Pass
--target-repo or --target-workflow to override the saved values.

Example usage:

    $ ods deploy edge
    $ ods deploy edge --ref user/my-feature
    $ ods deploy edge --ref user/my-feature --tag dev-build-my-feature-test`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			if err := deployEdge(opts, defaultRunPolling()); err != nil {
				log.Fatal(err)
			}
		},
	}

	cmd.Flags().StringVar(&opts.Ref, "ref", "", "Branch name or full commit SHA on origin to build instead of main")
	cmd.Flags().StringVar(&opts.Tag, "tag", "", "Tag to push for --ref instead of the derived dev-build-<branch>-<short-sha>; must start with dev-build-")
	cmd.Flags().StringVar(&opts.TargetRepo, "target-repo", "", "GitHub repo (owner/name) hosting the deploy workflows; shared across deploy subcommands; overrides saved config")
	cmd.Flags().StringVar(&opts.TargetWorkflow, "target-workflow", "", "Filename of the deploy workflow within the target repo; overrides saved config")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Perform local operations only; skip pushing the tag and dispatching workflows")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip the confirmation prompt")
	cmd.Flags().BoolVar(&opts.NoWaitDeploy, "no-wait-deploy", false, "Do not wait for the deploy workflow to finish after dispatching it")
	cmd.Flags().BoolVar(&opts.Verify, "verify", false, "Run pre-push hooks when pushing the tag; they are skipped by default")

	return cmd
}

func deployEdge(opts *DeployEdgeOptions, polling runPolling) error {
	git.CheckGitHubCLI()

	deployRepo, deployWorkflow, err := resolveDeployTarget(
		opts.TargetRepo,
		opts.TargetWorkflow,
		func(c *config.Config) *string { return &c.DeployEdge.TargetWorkflow },
	)
	if err != nil {
		return err
	}

	if !isMainRef(opts.Ref) {
		return deployBranchToEdge(opts, polling, deployRepo, deployWorkflow)
	}
	if opts.Tag != "" {
		return fatalErrorf("--tag needs --ref with a branch or commit other than main")
	}

	if opts.DryRun {
		log.Warning("=== DRY RUN MODE: tag push and workflow dispatch will be skipped (read-only gh and git fetch still run) ===")
	}

	if !opts.Yes {
		msg := "About to force-push tag 'edge' to origin/main and trigger an ad-hoc deploy. Continue? (Y/n): "
		if !prompt.Confirm(msg) {
			log.Info("Exiting...")
			return nil
		}
	}

	// Capture the most recent existing edge build run id BEFORE pushing, so we
	// can reliably identify the new run we trigger and not pick up a stale one.
	priorBuildRunID, err := latestWorkflowRunID(onyxRepo, deploymentWorkflowFile, "push", edgeTagName)
	if err != nil {
		return fatalErrorf("Failed to query existing deployment runs: %w", err)
	}
	log.Debugf("Most recent prior edge build run id: %d", priorBuildRunID)

	log.Info("Fetching origin/main...")
	if err := git.RunCommand("fetch", "origin", "main"); err != nil {
		return fatalErrorf("Failed to fetch origin/main: %w", err)
	}

	if opts.DryRun {
		log.Warnf("[DRY RUN] Would move local '%s' tag to origin/main", edgeTagName)
		log.Warnf("[DRY RUN] Would force-push tag '%s' to origin", edgeTagName)
		log.Warn("[DRY RUN] Would wait for build then dispatch the configured deploy workflow")
		return nil
	}

	log.Infof("Moving local '%s' tag to origin/main...", edgeTagName)
	if err := git.RunCommand("tag", "-f", edgeTagName, "origin/main"); err != nil {
		return fatalErrorf("Failed to move local tag: %w", err)
	}

	log.Infof("Force-pushing tag '%s' to origin...", edgeTagName)
	if err := git.PushTag(edgeTagName, true, opts.Verify); err != nil {
		return fatalErrorf("Failed to push edge tag: %w", err)
	}

	// Find the new build run, then poll it to completion.
	log.Info("Waiting for build workflow to start...")
	buildRun, err := waitForNewRun(polling, onyxRepo, deploymentWorkflowFile, "push", edgeTagName, priorBuildRunID)
	if err != nil {
		return fatalErrorf("Failed to find triggered build run: %w", err)
	}
	log.Infof("Build run started: %s", buildRun.URL)

	if err := waitForRunCompletion(polling, onyxRepo, buildRun.DatabaseID, buildPollTimeout, "build"); err != nil {
		return fatalErrorf("Build did not complete successfully: %w", err)
	}
	log.Info("Build completed successfully.")

	return dispatchEdgeDeploy(opts, polling, deployRepo, deployWorkflow, edgeTagName)
}

// dispatchEdgeDeploy dispatches the deploy workflow with version_tag=tag and,
// unless --no-wait-deploy is set, waits for it to finish.
func dispatchEdgeDeploy(opts *DeployEdgeOptions, polling runPolling, deployRepo, deployWorkflow, tag string) error {
	priorDeployRunID, err := latestWorkflowRunID(deployRepo, deployWorkflow, "workflow_dispatch", "")
	if err != nil {
		return fatalErrorf("Failed to query existing deploy runs: %w", err)
	}
	log.Debugf("Most recent prior deploy run id: %d", priorDeployRunID)

	log.Infof("Dispatching deploy workflow with version_tag=%s...", tag)
	if err := dispatchWorkflow(deployRepo, deployWorkflow, map[string]string{"version_tag": tag}); err != nil {
		return fatalErrorf("Failed to dispatch deploy workflow: %w", err)
	}

	deployRun, err := waitForNewRun(polling, deployRepo, deployWorkflow, "workflow_dispatch", "", priorDeployRunID)
	if err != nil {
		return fatalErrorf("Failed to find dispatched deploy run: %w", err)
	}
	log.Infof("Deploy run started: %s", deployRun.URL)
	log.Info("A kickoff Slack message will appear in the deployments Slack channel.")

	if opts.NoWaitDeploy {
		log.Info("--no-wait-deploy set; not waiting for deploy completion.")
		return nil
	}

	if err := waitForRunCompletion(polling, deployRepo, deployRun.DatabaseID, deployPollTimeout, "deploy"); err != nil {
		return fatalErrorf("Deploy did not complete successfully: %w", err)
	}
	log.Info("Deploy completed successfully.")
	return nil
}

// deployBranchToEdge builds opts.Ref under an immutable dev-build tag and
// deploys it.
func deployBranchToEdge(opts *DeployEdgeOptions, polling runPolling, deployRepo, deployWorkflow string) error {
	sha, err := resolveOriginCommit(opts.Ref)
	if err != nil {
		return fatalErrorf("Failed to resolve %s on origin: %w", opts.Ref, err)
	}

	tag := opts.Tag
	if tag == "" {
		tag = devBuildTagName(opts.Ref, sha)
	}
	if err := validateDevBuildTag(tag); err != nil {
		return fatalErrorf("Invalid tag %q: %w", tag, err)
	}

	existingSHA, err := remoteTagCommit(tag)
	if err != nil {
		return fatalErrorf("Failed to look up tag %s on origin: %w", tag, err)
	}
	if existingSHA != "" && existingSHA != sha {
		return fatalErrorf("Tag %s already exists on origin at %s, not %s; pass a different --tag", tag, shortSHA(existingSHA), shortSHA(sha))
	}
	reuseTag := existingSHA == sha
	log.Infof("Ref %s resolves to %s; tag %s", opts.Ref, sha, tag)

	if opts.DryRun {
		log.Warning("=== DRY RUN MODE: tag push and workflow dispatch will be skipped (read-only gh and git fetch still run) ===")
		if reuseTag {
			log.Warnf("[DRY RUN] Tag '%s' is already on origin at this commit; would wait for its build", tag)
		} else {
			log.Warnf("[DRY RUN] Would push tag '%s' at %s", tag, sha)
		}
		log.Warnf("[DRY RUN] Would wait for the build, then dispatch the configured deploy workflow with version_tag=%s", tag)
		return nil
	}

	if !opts.Yes {
		msg := fmt.Sprintf("About to build %s (%s) as %s and deploy it to the edge environment. Continue? (Y/n): ", opts.Ref, shortSHA(sha), tag)
		if !prompt.Confirm(msg) {
			log.Info("Exiting...")
			return nil
		}
	}

	// A reused tag accepts any earlier run of this commit; a new tag accepts
	// only the run its push starts.
	var priorBuildRunID int64
	if reuseTag {
		log.Infof("Tag '%s' is already on origin at %s; looking up its build run...", tag, shortSHA(sha))
	} else {
		priorBuildRunID, err = latestWorkflowRunID(onyxRepo, deploymentWorkflowFile, "push", tag)
		if err != nil {
			return fatalErrorf("Failed to query existing deployment runs: %w", err)
		}
		log.Infof("Pushing tag '%s' at %s...", tag, shortSHA(sha))
		if err := git.PushNewTag(sha, tag, opts.Verify); err != nil {
			return fatalErrorf("Failed to push tag %s: %w", tag, err)
		}
		log.Info("Waiting for build workflow to start...")
	}
	buildRun, err := waitForRunAtCommit(polling, onyxRepo, deploymentWorkflowFile, "push", tag, sha, priorBuildRunID)
	if err != nil {
		return fatalErrorf("Failed to find the build run for %s at %s: %w", tag, shortSHA(sha), err)
	}
	log.Infof("Build run: %s", buildRun.URL)

	if err := waitForRunCompletion(polling, onyxRepo, buildRun.DatabaseID, buildPollTimeout, "build"); err != nil {
		return fatalErrorf("Build did not complete successfully: %w", err)
	}
	log.Info("Build completed successfully.")

	return dispatchEdgeDeploy(opts, polling, deployRepo, deployWorkflow, tag)
}

// isMainRef reports whether ref names main, which deploys under the moving
// edge tag. An empty ref means main.
func isMainRef(ref string) bool {
	return ref == "" || ref == "main" || ref == "origin/main"
}

// resolveOriginCommit fetches ref (a branch name or full commit SHA) from
// origin and returns its commit SHA. The fetch fails when origin does not have
// the ref, so the returned commit is always one CI can check out.
func resolveOriginCommit(ref string) (string, error) {
	if err := git.RunCommand("fetch", "--quiet", "origin", ref); err != nil {
		return "", fmt.Errorf("origin does not have %s; push it first (pass a branch name or a full commit SHA): %w", ref, err)
	}
	return git.ResolveCommit("FETCH_HEAD")
}

// remoteTagCommit returns the commit that tag points at on origin, or "" when
// origin has no such tag.
func remoteTagCommit(tag string) (string, error) {
	ref := "refs/tags/" + tag
	output, err := exec.Command("git", "ls-remote", "origin", ref, ref+"^{}").Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return "", fmt.Errorf("git ls-remote failed: %w: %s", err, strings.TrimSpace(string(exitErr.Stderr)))
		}
		return "", fmt.Errorf("git ls-remote failed: %w", err)
	}
	// An annotated tag lists the tag object and the peeled commit (^{}); the
	// peeled line wins.
	commit := ""
	for _, line := range strings.Split(strings.TrimSpace(string(output)), "\n") {
		fields := strings.Fields(line)
		if len(fields) != 2 {
			continue
		}
		switch fields[1] {
		case ref + "^{}":
			return fields[0], nil
		case ref:
			commit = fields[0]
		}
	}
	return commit, nil
}

// devBuildTagName derives dev-build-<slug>-<short-sha> from ref. A full SHA
// ref has no useful slug, so the tag is dev-build-<short-sha>.
func devBuildTagName(ref, sha string) string {
	slug := ""
	if !fullCommitSHARe.MatchString(ref) {
		slug = devBuildSlug(ref)
	}
	if slug == "" {
		return release.DevBuildTagPrefix + shortSHA(sha)
	}
	return release.DevBuildTagPrefix + slug + "-" + shortSHA(sha)
}

// devBuildSlug turns a branch name into a tag-safe slug: the leading user/
// segment is dropped, the rest is lowercased, and runs of other characters
// become single dashes.
func devBuildSlug(branch string) string {
	branch = strings.TrimPrefix(branch, "origin/")
	if _, rest, found := strings.Cut(branch, "/"); found {
		branch = rest
	}
	slug := devBuildSlugInvalidRe.ReplaceAllString(strings.ToLower(branch), "-")
	slug = devBuildSlugDashesRe.ReplaceAllString(slug, "-")
	slug = strings.Trim(slug, "-")
	if len(slug) > devBuildSlugMaxLen {
		slug = strings.TrimRight(slug[:devBuildSlugMaxLen], "-")
	}
	return slug
}

// validateDevBuildTag rejects tags that the release environment or
// deployment.yml would not handle as a dev build.
func validateDevBuildTag(tag string) error {
	if !strings.HasPrefix(tag, release.DevBuildTagPrefix) || len(tag) == len(release.DevBuildTagPrefix) {
		return fmt.Errorf("must start with %s and have a name after it, because the release environment admits only %s* tags", release.DevBuildTagPrefix, release.DevBuildTagPrefix)
	}
	if strings.Contains(strings.ToLower(tag), "cloud") {
		return fmt.Errorf("must not contain \"cloud\", because tag names with \"cloud\" are kept for cloud releases")
	}
	if !dockerTagRe.MatchString(tag) {
		return fmt.Errorf("must be a valid Docker tag of at most 124 characters (letters, digits, '_', '.', '-')")
	}
	if err := exec.Command("git", "check-ref-format", "refs/tags/"+tag).Run(); err != nil {
		return fmt.Errorf("must be a valid git tag name (see git check-ref-format)")
	}
	return nil
}

// shortSHA truncates a commit SHA to the 7 characters used in image tags.
func shortSHA(sha string) string {
	if len(sha) > 7 {
		return sha[:7]
	}
	return sha
}
