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

// RunCommandVerboseOnError executes a git command and returns an error with
// stdout/stderr included if it fails. Useful for commands where hook output
// or other diagnostics are important on failure.
func RunCommandVerboseOnError(args ...string) error {
	log.Debugf("Running: git %s", strings.Join(args, " "))
	cmd := exec.Command("git", args...)

	output, err := cmd.CombinedOutput()
	if err != nil {
		if len(output) > 0 {
			return fmt.Errorf("%w\n%s", err, string(output))
		}
		return err
	}

	// Print output on success only if debug is enabled
	if log.IsLevelEnabled(log.DebugLevel) && len(output) > 0 {
		fmt.Print(string(output))
	}
	return nil
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

// StashResult holds the result of a stash operation
type StashResult struct {
	Stashed bool
}

// StashChanges stashes any uncommitted changes if present
// Returns a StashResult that should be passed to RestoreStash
func StashChanges() (*StashResult, error) {
	result := &StashResult{Stashed: false}
	if HasUncommittedChanges() {
		log.Info("Stashing uncommitted changes...")
		if err := RunCommand("stash", "--include-untracked"); err != nil {
			return nil, fmt.Errorf("failed to stash changes: %w", err)
		}
		result.Stashed = true
	}
	return result, nil
}

// RestoreStash restores previously stashed changes
func RestoreStash(result *StashResult) {
	if result == nil || !result.Stashed {
		return
	}
	log.Info("Restoring stashed changes...")
	if err := RunCommand("stash", "pop"); err != nil {
		log.Warnf("Failed to restore stashed changes (may have conflicts): %v", err)
		log.Info("Your changes are still in the stash. Run 'git stash pop' to restore them manually.")
	}
}

// CommitExistsOnBranch checks if a commit exists on a branch
func CommitExistsOnBranch(commitSHA, branchName string) bool {
	cmd := exec.Command("git", "branch", "--contains", commitSHA, "--list", branchName)
	output, err := cmd.Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(output)) != ""
}

// FetchCommit fetches a specific commit from the remote
func FetchCommit(commitSHA string) error {
	return FetchCommits([]string{commitSHA})
}

// FetchCommits fetches multiple commits from the remote in a single operation
func FetchCommits(commitSHAs []string) error {
	if len(commitSHAs) == 0 {
		return nil
	}

	if len(commitSHAs) == 1 {
		log.Infof("Fetching commit %s from origin", commitSHAs[0])
	} else {
		log.Infof("Fetching %d commits from origin", len(commitSHAs))
	}

	// Try to fetch all specific commits at once - this works if the remote allows it
	args := append([]string{"fetch", "--quiet", "origin"}, commitSHAs...)
	if err := RunCommand(args...); err != nil {
		// Fall back to fetching all refs if specific commit fetch fails
		log.Debugf("Specific commit fetch failed, fetching all: %v", err)
		if err := RunCommand("fetch", "--quiet", "origin"); err != nil {
			return fmt.Errorf("failed to fetch from origin: %w", err)
		}
	}
	return nil
}

// HasMergeConflict checks if the repository is in a merge conflict state
func HasMergeConflict() bool {
	// Check if there are unmerged files (indicates merge conflict)
	cmd := exec.Command("git", "diff", "--name-only", "--diff-filter=U")
	output, err := cmd.Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(output)) != ""
}

// IsCherryPickInProgress checks if a cherry-pick is currently in progress
func IsCherryPickInProgress() bool {
	cmd := exec.Command("git", "rev-parse", "--verify", "--quiet", "CHERRY_PICK_HEAD")
	return cmd.Run() == nil
}

// HasStagedChanges checks if there are staged changes in the index
func HasStagedChanges() bool {
	cmd := exec.Command("git", "diff", "--quiet", "--cached")
	return cmd.Run() != nil
}
