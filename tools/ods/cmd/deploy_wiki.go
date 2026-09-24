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
			if err := deployWiki(opts, defaultRunPolling()); err != nil {
				log.Fatal(err)
			}
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

func deployWiki(opts *DeployWikiOptions, polling runPolling) error {
	git.CheckGitHubCLI()

	deployRepo, deployWorkflow, err := resolveDeployTarget(
		opts.TargetRepo,
		opts.TargetWorkflow,
		func(c *config.Config) *string { return &c.DeployWiki.TargetWorkflow },
	)
	if err != nil {
		return err
	}

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
			return nil
		}
	}

	if !opts.NoBuild {
		if opts.DryRun {
			log.Warnf("[DRY RUN] Would dispatch %s in %s", wikiBuildWorkflow, wikiBuildRepo)
		} else {
			if err := runBuild(polling); err != nil {
				return err
			}
		}
	}

	if opts.DryRun {
		log.Warnf("[DRY RUN] Would dispatch %s in %s with version_tag=%s", deployWorkflow, deployRepo, versionTag)
		return nil
	}

	return runDeploy(polling, deployRepo, deployWorkflow, versionTag, opts.NoWaitDeploy)
}

func runBuild(polling runPolling) error {
	priorRunID, err := latestWorkflowRunID(wikiBuildRepo, wikiBuildWorkflow, "workflow_dispatch", "")
	if err != nil {
		return fatalErrorf("Failed to query existing build runs: %w", err)
	}
	log.Debugf("Most recent prior build run id: %d", priorRunID)

	log.Infof("Dispatching %s in %s...", wikiBuildWorkflow, wikiBuildRepo)
	if err := dispatchWorkflow(wikiBuildRepo, wikiBuildWorkflow, nil); err != nil {
		return fatalErrorf("Failed to dispatch build workflow: %w", err)
	}

	log.Info("Waiting for build workflow to start...")
	buildRun, err := waitForNewRun(polling, wikiBuildRepo, wikiBuildWorkflow, "workflow_dispatch", "", priorRunID)
	if err != nil {
		return fatalErrorf("Failed to find triggered build run: %w", err)
	}
	log.Infof("Build run started: %s", buildRun.URL)

	if err := waitForRunCompletion(polling, wikiBuildRepo, buildRun.DatabaseID, wikiBuildPollLimit, "build"); err != nil {
		return fatalErrorf("Build did not complete successfully: %w", err)
	}
	log.Info("Build completed successfully.")
	return nil
}

func runDeploy(polling runPolling, deployRepo, deployWorkflow, versionTag string, noWait bool) error {
	priorRunID, err := latestWorkflowRunID(deployRepo, deployWorkflow, "workflow_dispatch", "")
	if err != nil {
		return fatalErrorf("Failed to query existing deploy runs: %w", err)
	}
	log.Debugf("Most recent prior deploy run id: %d", priorRunID)

	log.Infof("Dispatching %s with version_tag=%s...", deployWorkflow, versionTag)
	if err := dispatchWorkflow(deployRepo, deployWorkflow, map[string]string{"version_tag": versionTag}); err != nil {
		return fatalErrorf("Failed to dispatch deploy workflow: %w", err)
	}

	log.Info("Waiting for deploy workflow to start...")
	deployRun, err := waitForNewRun(polling, deployRepo, deployWorkflow, "workflow_dispatch", "", priorRunID)
	if err != nil {
		return fatalErrorf("Failed to find dispatched deploy run: %w", err)
	}
	log.Infof("Deploy run started: %s", deployRun.URL)
	log.Info("A kickoff Slack message will appear in #monitor-deployments.")

	if noWait {
		log.Info("--no-wait-deploy set; not waiting for deploy completion.")
		return nil
	}

	if err := waitForRunCompletion(polling, deployRepo, deployRun.DatabaseID, wikiDeployPollLimit, "deploy"); err != nil {
		return fatalErrorf("Deploy did not complete successfully: %w", err)
	}
	log.Info("Deploy completed successfully.")
	return nil
}
