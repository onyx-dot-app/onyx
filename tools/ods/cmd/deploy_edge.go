package cmd

import (
	"encoding/json"
	"fmt"
	"os/exec"
	"sort"
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/config"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

const (
	onyxRepo               = "onyx-dot-app/onyx"
	deploymentWorkflowFile = "deployment.yml"
	edgeTagName            = "edge"

	// Polling configuration. Build runs typically take 20-30 minutes; deploys
	// are much shorter. The "discover" phase polls fast for a short window
	// because the run usually appears within seconds of pushing the tag /
	// dispatching the workflow.
	runDiscoveryInterval = 5 * time.Second
	runDiscoveryTimeout  = 2 * time.Minute
	runProgressInterval  = 30 * time.Second
	buildPollTimeout     = 60 * time.Minute
	deployPollTimeout    = 30 * time.Minute
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
filename. These are saved to the ods config file (~/.config/onyx-dev/config.json
on Linux/macOS) and reused on subsequent runs. Pass --target-repo or
--target-workflow to override the saved values.

Example usage:

    $ ods deploy edge`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			deployEdge(opts)
		},
	}

	cmd.Flags().StringVar(&opts.TargetRepo, "target-repo", "", "GitHub repo (owner/name) hosting the deploy workflow; overrides saved config")
	cmd.Flags().StringVar(&opts.TargetWorkflow, "target-workflow", "", "Filename of the deploy workflow within the target repo; overrides saved config")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Perform local operations only; skip pushing the tag and dispatching workflows")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip the confirmation prompt")
	cmd.Flags().BoolVar(&opts.NoWaitDeploy, "no-wait-deploy", false, "Do not wait for the deploy workflow to finish after dispatching it")

	return cmd
}

func deployEdge(opts *DeployEdgeOptions) {
	git.CheckGitHubCLI()

	deployRepo, deployWorkflow := resolveDeployTarget(opts)

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
	log.Info("A kickoff Slack message will appear in #monitor-deployments.")

	if opts.NoWaitDeploy {
		log.Info("--no-wait-deploy set; not waiting for deploy completion.")
		return
	}

	if err := waitForRunCompletion(deployRepo, deployRun.DatabaseID, deployPollTimeout, "deploy"); err != nil {
		log.Fatalf("Deploy did not complete successfully: %v", err)
	}
	log.Info("Deploy completed successfully.")
}

// resolveDeployTarget returns the deploy target repo and workflow to use,
// preferring explicit flags, then saved config, then prompting the user on
// first-time setup. Any newly-prompted values are persisted back to the
// config file so subsequent runs are non-interactive.
func resolveDeployTarget(opts *DeployEdgeOptions) (string, string) {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("Failed to load ods config: %v", err)
	}

	repo := opts.TargetRepo
	if repo == "" {
		repo = cfg.DeployEdge.TargetRepo
	}
	workflow := opts.TargetWorkflow
	if workflow == "" {
		workflow = cfg.DeployEdge.TargetWorkflow
	}

	prompted := false
	if repo == "" {
		log.Infof("First-time setup: ods will save your deploy target to %s", paths.ConfigFilePath())
		repo = prompt.String("Deploy target repo (owner/name): ")
		prompted = true
	}
	if workflow == "" {
		workflow = prompt.String("Deploy workflow filename (e.g. some-workflow.yml): ")
		prompted = true
	}

	if prompted {
		cfg.DeployEdge.TargetRepo = repo
		cfg.DeployEdge.TargetWorkflow = workflow
		if err := config.Save(cfg); err != nil {
			log.Fatalf("Failed to save ods config: %v", err)
		}
		log.Infof("Saved deploy target to %s", paths.ConfigFilePath())
	}

	return repo, workflow
}

// workflowRun is a partial representation of a `gh run list` JSON entry.
type workflowRun struct {
	DatabaseID int64  `json:"databaseId"`
	Status     string `json:"status"`
	Conclusion string `json:"conclusion"`
	URL        string `json:"url"`
	Event      string `json:"event"`
	HeadBranch string `json:"headBranch"`
}

// latestWorkflowRunID returns the highest databaseId for runs of the given
// workflow filtered by event (and optional branch). Returns 0 if no runs
// exist yet, which is a valid state.
func latestWorkflowRunID(repo, workflowFile, event, branch string) (int64, error) {
	runs, err := listWorkflowRuns(repo, workflowFile, event, branch, 10)
	if err != nil {
		return 0, err
	}
	var maxID int64
	for _, r := range runs {
		if r.DatabaseID > maxID {
			maxID = r.DatabaseID
		}
	}
	return maxID, nil
}

func listWorkflowRuns(repo, workflowFile, event, branch string, limit int) ([]workflowRun, error) {
	args := []string{
		"run", "list",
		"-R", repo,
		"--workflow", workflowFile,
		"--limit", fmt.Sprintf("%d", limit),
		"--json", "databaseId,status,conclusion,url,event,headBranch",
	}
	if event != "" {
		args = append(args, "--event", event)
	}
	if branch != "" {
		args = append(args, "--branch", branch)
	}
	cmd := exec.Command("gh", args...)
	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("gh run list failed: %w: %s", err, string(exitErr.Stderr))
		}
		return nil, fmt.Errorf("gh run list failed: %w", err)
	}
	var runs []workflowRun
	if err := json.Unmarshal(output, &runs); err != nil {
		return nil, fmt.Errorf("failed to parse gh run list output: %w", err)
	}
	// Sort newest-first by databaseId for predictable iteration.
	sort.Slice(runs, func(i, j int) bool { return runs[i].DatabaseID > runs[j].DatabaseID })
	return runs, nil
}

// waitForNewRun polls until a workflow run with databaseId > priorRunID
// appears, or the discovery timeout fires.
func waitForNewRun(repo, workflowFile, event, branch string, priorRunID int64) (*workflowRun, error) {
	deadline := time.Now().Add(runDiscoveryTimeout)
	for {
		runs, err := listWorkflowRuns(repo, workflowFile, event, branch, 5)
		if err != nil {
			return nil, err
		}
		for _, r := range runs {
			if r.DatabaseID > priorRunID {
				return &r, nil
			}
		}
		if time.Now().After(deadline) {
			return nil, fmt.Errorf("no new run appeared within %s", runDiscoveryTimeout)
		}
		time.Sleep(runDiscoveryInterval)
	}
}

// waitForRunCompletion polls a specific run until it reaches a terminal
// status. Returns an error if the run does not conclude with success or the
// timeout fires.
func waitForRunCompletion(repo string, runID int64, timeout time.Duration, label string) error {
	deadline := time.Now().Add(timeout)
	for {
		run, err := getRun(repo, runID)
		if err != nil {
			return err
		}
		log.Infof("[%s] run %d status=%s conclusion=%s", label, runID, run.Status, run.Conclusion)
		if run.Status == "completed" {
			if run.Conclusion == "success" {
				return nil
			}
			return fmt.Errorf("%s run %d concluded with status %q (see %s)", label, runID, run.Conclusion, run.URL)
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("%s run %d did not complete within %s (see %s)", label, runID, timeout, run.URL)
		}
		time.Sleep(runProgressInterval)
	}
}

func getRun(repo string, runID int64) (*workflowRun, error) {
	cmd := exec.Command(
		"gh", "run", "view", fmt.Sprintf("%d", runID),
		"-R", repo,
		"--json", "databaseId,status,conclusion,url,event,headBranch",
	)
	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("gh run view failed: %w: %s", err, string(exitErr.Stderr))
		}
		return nil, fmt.Errorf("gh run view failed: %w", err)
	}
	var run workflowRun
	if err := json.Unmarshal(output, &run); err != nil {
		return nil, fmt.Errorf("failed to parse gh run view output: %w", err)
	}
	return &run, nil
}

// dispatchWorkflow fires a workflow_dispatch event for the given workflow with
// the supplied string inputs.
func dispatchWorkflow(repo, workflowFile string, inputs map[string]string) error {
	args := []string{"workflow", "run", workflowFile, "-R", repo}
	for k, v := range inputs {
		args = append(args, "-f", fmt.Sprintf("%s=%s", k, v))
	}
	cmd := exec.Command("gh", args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("gh workflow run failed: %w: %s", err, string(output))
	}
	return nil
}
