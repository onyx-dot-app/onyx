package cmd

import (
	"os"
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

const (
	wikiBuildWorkflow   = "nightly-build.yml"
	wikiDeployWorkflow  = "dev-wiki-deploy.yml"
	wikiBuildPollLimit  = 30 * time.Minute
	wikiDeployPollLimit = 20 * time.Minute

	wikiBuildRepoEnv  = "ODS_WIKI_BUILD_REPO"
	wikiDeployRepoEnv = "ODS_WIKI_DEPLOY_REPO"
)

// wikiRepos returns the GitHub repos (org/name) hosting the wiki build and
// deploy workflows. They are read from the environment rather than hardcoded
// so that internal repo names don't live in this public repository.
func wikiRepos() (string, string) {
	buildRepo := os.Getenv(wikiBuildRepoEnv)
	deployRepo := os.Getenv(wikiDeployRepoEnv)
	if buildRepo == "" || deployRepo == "" {
		log.Fatalf("%s and %s must be set to the org/name of the wiki build and deploy repos", wikiBuildRepoEnv, wikiDeployRepoEnv)
	}
	return buildRepo, deployRepo
}

// DeployWikiOptions holds options for the deploy wiki command.
type DeployWikiOptions struct {
	DryRun       bool
	Yes          bool
	NoWaitDeploy bool
	NoBuild      bool
}

// NewDeployWikiCommand creates the `ods deploy wiki` command.
func NewDeployWikiCommand() *cobra.Command {
	opts := &DeployWikiOptions{}

	cmd := &cobra.Command{
		Use:   "wiki",
		Short: "Build a fresh nightly image and deploy it to dev-wiki.onyx.app",
		Long: `Build a fresh nightly image of agent-wiki and deploy it to dev-wiki.

This command will:
  1. Dispatch the nightly-build.yml workflow in the wiki build repo
     ($ODS_WIKI_BUILD_REPO), which builds and pushes the
     nightly-latest-YYYYMMDD images
  2. Wait for the build workflow to finish
  3. Dispatch the dev-wiki-deploy.yml workflow in the wiki deploy repo
     ($ODS_WIKI_DEPLOY_REPO) with version_tag=nightly-latest-YYYYMMDD
     (today's UTC date)
  4. Wait for the deploy workflow to finish

Requires $ODS_WIKI_BUILD_REPO and $ODS_WIKI_DEPLOY_REPO to be set to the
org/name of the wiki build and deploy repos.

All GitHub operations run through the gh CLI, so authorization is enforced
by your gh credentials and GitHub's repo/workflow permissions. A kickoff
Slack message will appear in the deployments Slack channel.

Pass --no-build to skip step 1 and just deploy whatever's already on
Docker Hub for today's tag.

Example usage:

    $ ods deploy wiki`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			deployWiki(opts)
		},
	}

	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Perform local operations only; skip dispatching workflows")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip the confirmation prompt")
	cmd.Flags().BoolVar(&opts.NoWaitDeploy, "no-wait-deploy", false, "Do not wait for the deploy workflow to finish after dispatching it")
	cmd.Flags().BoolVar(&opts.NoBuild, "no-build", false, "Skip the build step; deploy whatever's already on Docker Hub for today's tag")

	return cmd
}

func deployWiki(opts *DeployWikiOptions) {
	git.CheckGitHubCLI()
	buildRepo, deployRepo := wikiRepos()

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
			log.Warnf("[DRY RUN] Would dispatch %s in %s", wikiBuildWorkflow, buildRepo)
		} else {
			runBuild(buildRepo)
		}
	}

	if opts.DryRun {
		log.Warnf("[DRY RUN] Would dispatch %s in %s with version_tag=%s", wikiDeployWorkflow, deployRepo, versionTag)
		return
	}

	runDeploy(deployRepo, versionTag, opts.NoWaitDeploy)
}

func runBuild(buildRepo string) {
	priorRunID, err := latestWorkflowRunID(buildRepo, wikiBuildWorkflow, "workflow_dispatch", "")
	if err != nil {
		log.Fatalf("Failed to query existing build runs: %v", err)
	}
	log.Debugf("Most recent prior build run id: %d", priorRunID)

	log.Infof("Dispatching %s in %s...", wikiBuildWorkflow, buildRepo)
	if err := dispatchWorkflow(buildRepo, wikiBuildWorkflow, nil); err != nil {
		log.Fatalf("Failed to dispatch build workflow: %v", err)
	}

	log.Info("Waiting for build workflow to start...")
	buildRun, err := waitForNewRun(buildRepo, wikiBuildWorkflow, "workflow_dispatch", "", priorRunID)
	if err != nil {
		log.Fatalf("Failed to find triggered build run: %v", err)
	}
	log.Infof("Build run started: %s", buildRun.URL)

	if err := waitForRunCompletion(buildRepo, buildRun.DatabaseID, wikiBuildPollLimit, "build"); err != nil {
		log.Fatalf("Build did not complete successfully: %v", err)
	}
	log.Info("Build completed successfully.")
}

func runDeploy(deployRepo string, versionTag string, noWait bool) {
	priorRunID, err := latestWorkflowRunID(deployRepo, wikiDeployWorkflow, "workflow_dispatch", "")
	if err != nil {
		log.Fatalf("Failed to query existing deploy runs: %v", err)
	}
	log.Debugf("Most recent prior deploy run id: %d", priorRunID)

	log.Infof("Dispatching %s with version_tag=%s...", wikiDeployWorkflow, versionTag)
	if err := dispatchWorkflow(deployRepo, wikiDeployWorkflow, map[string]string{"version_tag": versionTag}); err != nil {
		log.Fatalf("Failed to dispatch deploy workflow: %v", err)
	}

	log.Info("Waiting for deploy workflow to start...")
	deployRun, err := waitForNewRun(deployRepo, wikiDeployWorkflow, "workflow_dispatch", "", priorRunID)
	if err != nil {
		log.Fatalf("Failed to find dispatched deploy run: %v", err)
	}
	log.Infof("Deploy run started: %s", deployRun.URL)
	log.Info("A kickoff Slack message will appear in the deployments Slack channel.")

	if noWait {
		log.Info("--no-wait-deploy set; not waiting for deploy completion.")
		return
	}

	if err := waitForRunCompletion(deployRepo, deployRun.DatabaseID, wikiDeployPollLimit, "deploy"); err != nil {
		log.Fatalf("Deploy did not complete successfully: %v", err)
	}
	log.Info("Deploy completed successfully.")
}
