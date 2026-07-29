package cmd

import (
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/config"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

const (
	onyxRepo               = "onyx-dot-app/onyx"
	deploymentWorkflowFile = "deployment.yml"
	edgeTagName            = "edge"

	// Build runs typically take 20-30 minutes; deploys are much shorter.
	buildPollTimeout  = 60 * time.Minute
	deployPollTimeout = 30 * time.Minute
)

// DeployEdgeOptions holds options for the deploy edge command.
type DeployEdgeOptions struct {
	TargetRepo     string
	TargetWorkflow string
	DryRun         bool
	Yes            bool
	NoWaitDeploy   bool
}

// NewDeployEdgeCommand creates the `ods deploy edge` command.
func NewDeployEdgeCommand() *cobra.Command {
	opts := &DeployEdgeOptions{}

	cmd := &cobra.Command{
		Use:   "edge",
		Short: "Build edge images off main and deploy to the configured target",
		Long: `Build edge images off origin/main and dispatch the configured deploy workflow.

This command will:
  1. Force-push the 'edge' tag to origin/main, triggering the build
  2. Wait for the build workflow to finish
  3. Dispatch the configured deploy workflow with version_tag=edge
  4. Wait for the deploy workflow to finish

All GitHub operations run through the gh CLI, so authorization is enforced
by your gh credentials and GitHub's repo/workflow permissions.

On first run, you'll be prompted for the deploy target repo and workflow
filename, saved to the ods config file (~/.config/onyx-dev/config.json on
Linux/macOS) and reused on subsequent runs. The target repo is shared across
all deploy subcommands; the workflow filename is per-subcommand. Pass
--target-repo or --target-workflow to override the saved values.

Example usage:

    $ ods deploy edge`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			deployEdge(opts)
		},
	}

	cmd.Flags().StringVar(&opts.TargetRepo, "target-repo", "", "GitHub repo (owner/name) hosting the deploy workflows; shared across deploy subcommands; overrides saved config")
	cmd.Flags().StringVar(&opts.TargetWorkflow, "target-workflow", "", "Filename of the deploy workflow within the target repo; overrides saved config")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Perform local operations only; skip pushing the tag and dispatching workflows")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip the confirmation prompt")
	cmd.Flags().BoolVar(&opts.NoWaitDeploy, "no-wait-deploy", false, "Do not wait for the deploy workflow to finish after dispatching it")

	return cmd
}

func deployEdge(opts *DeployEdgeOptions) {
	git.CheckGitHubCLI()

	deployRepo, deployWorkflow := resolveDeployTarget(
		opts.TargetRepo,
		opts.TargetWorkflow,
		func(c *config.Config) *string { return &c.DeployEdge.TargetWorkflow },
	)

	if opts.DryRun {
		log.Warning("=== DRY RUN MODE: tag push and workflow dispatch will be skipped (read-only gh and git fetch still run) ===")
	}

	if !opts.Yes {
		msg := "About to force-push tag 'edge' to origin/main and trigger an ad-hoc deploy. Continue? (Y/n): "
		if !prompt.Confirm(msg) {
			log.Info("Exiting...")
			return
		}
	}

	// Capture the most recent existing edge build run id BEFORE pushing, so we
	// can reliably identify the new run we trigger and not pick up a stale one.
	priorBuildRunID, err := latestWorkflowRunID(onyxRepo, deploymentWorkflowFile, "push", edgeTagName)
	if err != nil {
		log.Fatalf("Failed to query existing deployment runs: %v", err)
	}
	log.Debugf("Most recent prior edge build run id: %d", priorBuildRunID)

	log.Info("Fetching origin/main...")
	if err := git.RunCommand("fetch", "origin", "main"); err != nil {
		log.Fatalf("Failed to fetch origin/main: %v", err)
	}

	if opts.DryRun {
		log.Warnf("[DRY RUN] Would move local '%s' tag to origin/main", edgeTagName)
		log.Warnf("[DRY RUN] Would force-push tag '%s' to origin", edgeTagName)
		log.Warn("[DRY RUN] Would wait for build then dispatch the configured deploy workflow")
		return
	}

	log.Infof("Moving local '%s' tag to origin/main...", edgeTagName)
	if err := git.RunCommand("tag", "-f", edgeTagName, "origin/main"); err != nil {
		log.Fatalf("Failed to move local tag: %v", err)
	}

	log.Infof("Force-pushing tag '%s' to origin...", edgeTagName)
	if err := git.RunCommand("push", "-f", "origin", edgeTagName); err != nil {
		log.Fatalf("Failed to push edge tag: %v", err)
	}

	// Find the new build run, then poll it to completion.
	log.Info("Waiting for build workflow to start...")
	buildRun, err := waitForNewRun(onyxRepo, deploymentWorkflowFile, "push", edgeTagName, priorBuildRunID)
	if err != nil {
		log.Fatalf("Failed to find triggered build run: %v", err)
	}
	log.Infof("Build run started: %s", buildRun.URL)

	if err := waitForRunCompletion(onyxRepo, buildRun.DatabaseID, buildPollTimeout, "build"); err != nil {
		log.Fatalf("Build did not complete successfully: %v", err)
	}
	log.Info("Build completed successfully.")

	// Dispatch the deploy workflow.
	priorDeployRunID, err := latestWorkflowRunID(deployRepo, deployWorkflow, "workflow_dispatch", "")
	if err != nil {
		log.Fatalf("Failed to query existing deploy runs: %v", err)
	}
	log.Debugf("Most recent prior deploy run id: %d", priorDeployRunID)

	log.Info("Dispatching deploy workflow with version_tag=edge...")
	if err := dispatchWorkflow(deployRepo, deployWorkflow, map[string]string{"version_tag": edgeTagName}); err != nil {
		log.Fatalf("Failed to dispatch deploy workflow: %v", err)
	}

	deployRun, err := waitForNewRun(deployRepo, deployWorkflow, "workflow_dispatch", "", priorDeployRunID)
	if err != nil {
		log.Fatalf("Failed to find dispatched deploy run: %v", err)
	}
	log.Infof("Deploy run started: %s", deployRun.URL)
	log.Info("A kickoff Slack message will appear in the deployments Slack channel.")

	if opts.NoWaitDeploy {
		log.Info("--no-wait-deploy set; not waiting for deploy completion.")
		return
	}

	if err := waitForRunCompletion(deployRepo, deployRun.DatabaseID, deployPollTimeout, "deploy"); err != nil {
		log.Fatalf("Deploy did not complete successfully: %v", err)
	}
	log.Info("Deploy completed successfully.")
}
