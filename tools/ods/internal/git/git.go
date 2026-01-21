package git

import (
	"fmt"
	"os"
	"os/exec"
	"strings"

	log "github.com/sirupsen/logrus"
)

// CheckGitHubCLI checks if the GitHub CLI is installed and exits with a helpful message if not
func CheckGitHubCLI() {
	cmd := exec.Command("gh", "--version")
	if err := cmd.Run(); err != nil {
		log.Fatal("GitHub CLI (gh) is not installed. Please install it from https://cli.github.com/")
	}
}

// GetCurrentBranch returns the name of the current git branch
func GetCurrentBranch() (string, error) {
	cmd := exec.Command("git", "branch", "--show-current")
	output, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("git branch failed: %w", err)
	}
	return strings.TrimSpace(string(output)), nil
}

// RunCommand executes a git command and returns any error
func RunCommand(args ...string) error {
	log.Debugf("Running: git %s", strings.Join(args, " "))
	cmd := exec.Command("git", args...)
	if log.IsLevelEnabled(log.DebugLevel) {
		cmd.Stdout = os.Stdout
	}
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

// GetCommitMessage gets the first line of a commit message
func GetCommitMessage(commitSHA string) (string, error) {
	cmd := exec.Command("git", "log", "-1", "--format=%s", commitSHA)
	output, err := cmd.Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(output)), nil
}

// BranchExists checks if a local git branch exists
func BranchExists(branchName string) bool {
	cmd := exec.Command("git", "show-ref", "--verify", "--quiet", fmt.Sprintf("refs/heads/%s", branchName))
	return cmd.Run() == nil
}

// HasUncommittedChanges checks if there are uncommitted changes in the working directory
func HasUncommittedChanges() bool {
	// git diff --quiet returns exit code 1 if there are changes
	staged := exec.Command("git", "diff", "--quiet", "--cached")
	unstaged := exec.Command("git", "diff", "--quiet")
	return staged.Run() != nil || unstaged.Run() != nil
}
