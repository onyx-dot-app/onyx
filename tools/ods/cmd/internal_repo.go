package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// internalRepoVariable is the onyx repo variable that names the internal infra
// repo (owner/name). deployment.yml sends the cloud image dispatch to it, and
// it also holds agent-context/. The name is not committed to this repo.
const internalRepoVariable = "CLOUD_DEPLOYMENT_REPO"

// resolveInternalRepo returns the internal infra repo as owner/name: from
// envVar when set, else from the onyx repo variable through gh, which needs
// read access to the variables of onyx.
func resolveInternalRepo(envVar string) (string, error) {
	if repo := strings.TrimSpace(os.Getenv(envVar)); repo != "" {
		return repo, nil
	}
	output, err := exec.Command("gh", "variable", "get", internalRepoVariable, "-R", onyxRepo).Output()
	if err != nil {
		detail := ""
		if exitErr, ok := err.(*exec.ExitError); ok {
			detail = ": " + strings.TrimSpace(string(exitErr.Stderr))
		}
		return "", fmt.Errorf(
			"could not read the %s variable of %s (%w%s)\n  Set %s to the internal infra repo (owner/name) instead",
			internalRepoVariable, onyxRepo, err, detail, envVar,
		)
	}
	repo := strings.TrimSpace(string(output))
	if repo == "" {
		return "", fmt.Errorf("the %s variable of %s is empty; set %s to the internal infra repo (owner/name)",
			internalRepoVariable, onyxRepo, envVar)
	}
	return repo, nil
}
