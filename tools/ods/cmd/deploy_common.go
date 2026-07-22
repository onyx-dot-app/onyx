package cmd

import (
	"encoding/json"
	"fmt"
	"os/exec"
	"sort"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/config"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

const (
	// Polling configuration shared by the deploy subcommands. The "discover"
	// phase polls fast for a short window because a run usually appears within
	// seconds of pushing the tag / dispatching the workflow.
	runDiscoveryInterval = 5 * time.Second
	runDiscoveryTimeout  = 2 * time.Minute
	runProgressInterval  = 30 * time.Second
)

// resolveDeployTarget returns the deploy target repo and workflow to use,
// preferring explicit flags, then saved config, then prompting the user on
// first-time setup. The repo is shared by all deploy subcommands (read from and
// persisted to config.Deploy.TargetRepo), so it is only entered once; the
// workflowSelector picks which per-command section holds the workflow filename
// (e.g. DeployEdge vs DeployWiki). Any newly-prompted values are persisted back
// to the config file so subsequent runs are non-interactive.
func resolveDeployTarget(flagRepo, flagWorkflow string, workflowSelector func(*config.Config) *string) (string, string) {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("Failed to load ods config: %v", err)
	}
	repoPtr := &cfg.Deploy.TargetRepo
	workflowPtr := workflowSelector(cfg)

	repo := flagRepo
	if repo == "" {
		repo = *repoPtr
	}
	workflow := flagWorkflow
	if workflow == "" {
		workflow = *workflowPtr
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
		*repoPtr = repo
		*workflowPtr = workflow
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
