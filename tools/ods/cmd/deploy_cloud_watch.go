package cmd

import (
	"encoding/json"
	"fmt"
	"os/exec"
	"time"

	log "github.com/sirupsen/logrus"
)

const (
	// Mirrors the CLOUD_DEPLOYMENT_REPO repo variable that deployment.yml's
	// dispatch-cloud-deployment job sends the new-cloud-image dispatch to.
	cloudDeploymentRepo = "onyx-dot-app/onyx-infra"
	// The workflow in cloudDeploymentRepo that opens the version bump PR.
	bumpWorkflowFile = "bump-cloud-version.yml"
	// The bump workflow opens its PR from the branch bump-version/<tag>.
	bumpPRBranchPrefix = "bump-version/"

	// The deployment.yml job that sends the new-cloud-image dispatch; its
	// success means the bump workflow was triggered.
	dispatchJobName = "dispatch-cloud-deployment"

	// The bump workflow usually opens the PR within a few minutes of the
	// dispatch at the end of the build. The window covers its 15-minute job
	// timeout plus runner queue delay.
	bumpPRDiscoveryTimeout = 20 * time.Minute
	bumpPRPollInterval     = 15 * time.Second
)

// watchCloudRelease follows the release pipeline of an already-pushed cloud
// tag: the deployment.yml build, then the bump PR that the dispatched bump
// workflow opens in the infra repo. Everything here is read-only polling, so
// interrupting or re-running it is always safe.
func watchCloudRelease(tag string) error {
	log.Info("Looking up the deployment run...")
	// A cloud tag is unique per push and never reused, so any run on this
	// branch is the right one. A prior-run-id floor above 0 would also break
	// re-attaching to runs that started before newer releases.
	run, err := waitForNewRun(onyxRepo, deploymentWorkflowFile, "push", tag, 0)
	if err != nil {
		return fmt.Errorf(
			"could not find the deployment run for %s (see https://github.com/%s/actions/workflows/%s): %w",
			tag, onyxRepo, deploymentWorkflowFile, err)
	}
	log.Infof("Deployment run: %s", run.URL)
	fmt.Println(run.URL)

	// A failed or timed-out run does not always mean no PR: the dispatch job
	// can succeed while an unrelated job fails. Whether that job succeeded
	// decides if a PR is worth waiting for.
	if buildErr := waitForRunCompletion(onyxRepo, run.DatabaseID, buildPollTimeout, "build"); buildErr != nil {
		log.Warnf("Deployment run did not succeed: %v", buildErr)
		dispatched, err := dispatchJobSucceeded(run.DatabaseID)
		if err != nil {
			log.Warnf("Could not check the bump dispatch job: %v", err)
			return buildErr
		}
		if !dispatched {
			log.Warn("The bump dispatch has not succeeded, so a bump PR is not expected.")
			return buildErr
		}
		log.Info("The bump dispatch succeeded; waiting for the bump PR...")
		pr, err := waitForBumpPR(tag)
		if err != nil {
			log.Warnf("Bump PR lookup failed: %v", err)
			return buildErr
		}
		log.Warn("The deployment run did not succeed; review it before approving.")
		announceBumpPR(pr)
		return nil
	}

	log.Info("Build completed; waiting for the bump PR...")
	pr, err := waitForBumpPR(tag)
	if err != nil {
		return fmt.Errorf("%w; check https://github.com/%s/actions/workflows/%s", err, cloudDeploymentRepo, bumpWorkflowFile)
	}
	announceBumpPR(pr)
	return nil
}

// announceBumpPR prints the bump PR, wording the log line by PR state: a
// re-attached watch can find a PR that was already merged or closed.
func announceBumpPR(pr *pullRequest) {
	switch pr.State {
	case "MERGED":
		log.Infof("Bump PR already merged: %s", pr.URL)
	case "CLOSED":
		log.Warnf("Bump PR was closed without merging: %s", pr.URL)
	default:
		log.Infof("Bump PR ready for approval: %s", pr.URL)
	}
	fmt.Println(pr.URL)
}

// waitForBumpPR polls until the bump PR for tag exists or the discovery timeout
// fires.
func waitForBumpPR(tag string) (*pullRequest, error) {
	deadline := time.Now().Add(bumpPRDiscoveryTimeout)
	for {
		pr, err := findBumpPR(tag)
		if err != nil {
			return nil, err
		}
		if pr != nil {
			return pr, nil
		}
		if time.Now().After(deadline) {
			return nil, fmt.Errorf("no bump PR for %s appeared within %s", tag, bumpPRDiscoveryTimeout)
		}
		time.Sleep(bumpPRPollInterval)
	}
}

// dispatchJobSucceeded reports whether the run's bump dispatch job concluded
// successfully. A job that is missing, skipped, or still running counts as not
// dispatched.
func dispatchJobSucceeded(runID int64) (bool, error) {
	cmd := exec.Command(
		"gh", "run", "view", fmt.Sprintf("%d", runID),
		"-R", onyxRepo,
		"--json", "jobs",
	)
	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return false, fmt.Errorf("gh run view failed: %w: %s", err, string(exitErr.Stderr))
		}
		return false, fmt.Errorf("gh run view failed: %w", err)
	}
	var run struct {
		Jobs []struct {
			Name       string `json:"name"`
			Conclusion string `json:"conclusion"`
		} `json:"jobs"`
	}
	if err := json.Unmarshal(output, &run); err != nil {
		return false, fmt.Errorf("failed to parse gh run view output: %w", err)
	}
	for _, job := range run.Jobs {
		if job.Name == dispatchJobName {
			return job.Conclusion == "success", nil
		}
	}
	return false, nil
}

// pullRequest is a partial representation of a gh pr list JSON entry.
type pullRequest struct {
	Number int    `json:"number"`
	State  string `json:"state"`
	URL    string `json:"url"`
}

// findBumpPR returns the bump PR for tag, or nil when none exists yet. Bump
// branches are bot-owned with one branch per tag, so the head-branch filter
// identifies the PR exactly.
func findBumpPR(tag string) (*pullRequest, error) {
	cmd := exec.Command(
		"gh", "pr", "list",
		"-R", cloudDeploymentRepo,
		"--head", bumpPRBranchPrefix+tag,
		"--state", "all",
		"--json", "number,state,url",
	)
	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("gh pr list failed: %w: %s", err, string(exitErr.Stderr))
		}
		return nil, fmt.Errorf("gh pr list failed: %w", err)
	}
	var prs []pullRequest
	if err := json.Unmarshal(output, &prs); err != nil {
		return nil, fmt.Errorf("failed to parse gh pr list output: %w", err)
	}
	if len(prs) == 0 {
		return nil, nil
	}
	return &prs[0], nil
}
