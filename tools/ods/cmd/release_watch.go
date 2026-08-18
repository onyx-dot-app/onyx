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

	// The bump workflow usually opens the PR within a few minutes of the
	// dispatch at the end of the build; its own timeout is 15 minutes.
	bumpPRDiscoveryTimeout = 10 * time.Minute
	bumpPRPollInterval     = 15 * time.Second
)

// watchCloudRelease follows the release pipeline of an already-pushed cloud
// tag: the deployment.yml build, then the bump PR that the dispatched bump
// workflow opens in the infra repo. Everything here is read-only polling, so
// interrupting or re-running it is always safe.
func watchCloudRelease(tag string) error {
	log.Info("Looking up the deployment run...")
	run, err := waitForNewRun(onyxRepo, deploymentWorkflowFile, "push", tag, 0)
	if err != nil {
		return fmt.Errorf(
			"could not find the deployment run for %s (see https://github.com/%s/actions/workflows/%s): %w",
			tag, onyxRepo, deploymentWorkflowFile, err)
	}
	log.Infof("Deployment run: %s", run.URL)
	fmt.Println(run.URL)

	// A failed or timed-out run does not always mean no PR: the dispatch job
	// can succeed while an unrelated job fails, and the bump workflow can also
	// be dispatched manually. Check once for the PR before giving up.
	if buildErr := waitForRunCompletion(onyxRepo, run.DatabaseID, buildPollTimeout, "build"); buildErr != nil {
		log.Warnf("Deployment run did not succeed: %v", buildErr)
		pr, err := findBumpPR(tag)
		if err != nil || pr == nil {
			return buildErr
		}
		log.Warn("A bump PR exists anyway; review the run before approving.")
		log.Infof("Bump PR: %s", pr.URL)
		fmt.Println(pr.URL)
		return nil
	}

	log.Info("Build completed; waiting for the bump PR...")
	pr, err := waitForBumpPR(tag)
	if err != nil {
		return fmt.Errorf("%w; check https://github.com/%s/actions/workflows/%s", err, cloudDeploymentRepo, bumpWorkflowFile)
	}
	log.Infof("Bump PR ready for approval: %s", pr.URL)
	fmt.Println(pr.URL)
	return nil
}

// waitForBumpPR polls until the bump PR for tag exists or the discovery
// timeout fires.
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
