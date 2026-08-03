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
	wikiBuildRepo       = "onyx-dot-app/agent-wiki"
	wikiBuildWorkflow   = "nightly-build.yml"
	wikiBuildPollLimit  = 30 * time.Minute
	wikiDeployPollLimit = 20 * time.Minute
)

// DeployWikiOptions holds options for the deploy wiki command.
type DeployWikiOptions struct {
	TargetRepo     string
	TargetWorkflow string
	DryRun         bool
	Yes            bool
	NoWaitDeploy   bool
	NoBuild        bool
}

// NewDeployWikiCommand creates the `ods deploy wiki` command.
func NewDeployWikiCommand() *cobra.Command {
	opts := &DeployWikiOptions{}

	cmd := &cobra.Command{
		Use:   "wiki",
		Short: "Build a fresh nightly image and deploy it to dev-wiki.onyx.app",
		Long: `Build a fresh nightly image of agent-wiki and deploy it to dev-wiki.

This command will:
  1. Dispatch the nightly-build.yml workflow in onyx-dot-app/agent-wiki
     (builds and pushes onyxdotapp/agent-wiki-{backend,frontend}:nightly-latest-YYYYMMDD)
  2. Wait for the build workflow to finish
  3. Dispatch the configured deploy workflow with version_tag=nightly-latest-YYYYMMDD
     (today's UTC date)
  4. Wait for the deploy workflow to finish

All GitHub operations run through the gh CLI, so authorization is enforced
by your gh credentials and GitHub's repo/workflow permissions. A kickoff
Slack message will appear in #monitor-deployments.

On first run, you'll be prompted for the deploy target repo and workflow
filename, saved to the ods config file (~/.config/onyx-dev/config.json on
Linux/macOS) and reused on subsequent runs. The target repo is shared across
all deploy subcommands; the workflow filename is per-subcommand. Pass
--target-repo or --target-workflow to override the saved values.

Pass --no-build to skip step 1 and just deploy whatever's already on
Docker Hub for today's tag.

Example usage:

    $ ods deploy wiki`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			deployWiki(opts)
		},
	}

	cmd.Flags().StringVar(&opts.TargetRepo, "target-repo", "", "GitHub repo (owner/name) hosting the deploy workflows; shared across deploy subcommands; overrides saved config")
	cmd.Flags().StringVar(&opts.TargetWorkflow, "target-workflow", "", "Filename of the deploy workflow within the target repo; overrides saved config")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Perform local operations only; skip dispatching workflows")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip the confirmation prompt")
	cmd.Flags().BoolVar(&opts.NoWaitDeploy, "no-wait-deploy", false, "Do not wait for the deploy workflow to finish after dispatching it")
	cmd.Flags().BoolVar(&opts.NoBuild, "no-build", false, "Skip the build step; deploy whatever's already on Docker Hub for today's tag")

	return cmd
}

func deployWiki(opts *DeployWikiOptions) {
	git.CheckGitHubCLI()

	deployRepo, deployWorkflow := resolveDeployTarget(
		opts.TargetRepo,
		opts.TargetWorkflow,
		func(c *config.Config) *string { return &c.DeployWiki.TargetWorkflow },
	)

	if opts.DryRun {
		log.Warning("=== DRY RUN MODE: workflow dispatches will be skipped ===")
	}

	versionTag := "nightly-latest-" + time.Now().UTC().Format("20060102")
	log.Infof("Target version tag: %s", versionTag)

	if !opts.Yes {
		var msg string
		if opts.NoBuild {
			msg = "About to deploy " + versionTag + " to dev-wiki.onyx.app (no rebuild). Continue? (Y/n): "
		} else {
			msg = "About to build a fresh agent-wiki image and deploy it to dev-wiki.onyx.app. Continue? (Y/n): "
		}
		if !prompt.Confirm(msg) {
			log.Info("Exiting...")
			return
		}
	}

	if !opts.NoBuild {
		if opts.DryRun {
			log.Warnf("[DRY RUN] Would dispatch %s in %s", wikiBuildWorkflow, wikiBuildRepo)
		} else {
			runBuild()
		}
	}

	if opts.DryRun {
		log.Warnf("[DRY RUN] Would dispatch %s in %s with version_tag=%s", deployWorkflow, deployRepo, versionTag)
		return
	}

	runDeploy(deployRepo, deployWorkflow, versionTag, opts.NoWaitDeploy)
}

func runBuild() {
	priorRunID, err := latestWorkflowRunID(wikiBuildRepo, wikiBuildWorkflow, "workflow_dispatch", "")
	if err != nil {
		log.Fatalf("Failed to query existing build runs: %v", err)
	}
	log.Debugf("Most recent prior build run id: %d", priorRunID)

	log.Infof("Dispatching %s in %s...", wikiBuildWorkflow, wikiBuildRepo)
	if err := dispatchWorkflow(wikiBuildRepo, wikiBuildWorkflow, nil); err != nil {
		log.Fatalf("Failed to dispatch build workflow: %v", err)
	}

	log.Info("Waiting for build workflow to start...")
	buildRun, err := waitForNewRun(wikiBuildRepo, wikiBuildWorkflow, "workflow_dispatch", "", priorRunID)
	if err != nil {
		log.Fatalf("Failed to find triggered build run: %v", err)
	}
	log.Infof("Build run started: %s", buildRun.URL)

	if err := waitForRunCompletion(wikiBuildRepo, buildRun.DatabaseID, wikiBuildPollLimit, "build"); err != nil {
		log.Fatalf("Build did not complete successfully: %v", err)
	}
	log.Info("Build completed successfully.")
}

func runDeploy(deployRepo, deployWorkflow, versionTag string, noWait bool) {
	priorRunID, err := latestWorkflowRunID(deployRepo, deployWorkflow, "workflow_dispatch", "")
	if err != nil {
		log.Fatalf("Failed to query existing deploy runs: %v", err)
	}
	log.Debugf("Most recent prior deploy run id: %d", priorRunID)

	log.Infof("Dispatching %s with version_tag=%s...", deployWorkflow, versionTag)
	if err := dispatchWorkflow(deployRepo, deployWorkflow, map[string]string{"version_tag": versionTag}); err != nil {
		log.Fatalf("Failed to dispatch deploy workflow: %v", err)
	}

	log.Info("Waiting for deploy workflow to start...")
	deployRun, err := waitForNewRun(deployRepo, deployWorkflow, "workflow_dispatch", "", priorRunID)
	if err != nil {
		log.Fatalf("Failed to find dispatched deploy run: %v", err)
	}
	log.Infof("Deploy run started: %s", deployRun.URL)
	log.Info("A kickoff Slack message will appear in #monitor-deployments.")

	if noWait {
		log.Info("--no-wait-deploy set; not waiting for deploy completion.")
		return
	}

	if err := waitForRunCompletion(deployRepo, deployRun.DatabaseID, wikiDeployPollLimit, "deploy"); err != nil {
		log.Fatalf("Deploy did not complete successfully: %v", err)
	}
	log.Info("Deploy completed successfully.")
}
