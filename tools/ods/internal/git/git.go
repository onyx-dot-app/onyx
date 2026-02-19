package git

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
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

// GetGitDir returns the worktree-aware .git directory
func GetGitDir() (string, error) {
	cmd := exec.Command("git", "rev-parse", "--git-dir")
	output, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("git rev-parse --git-dir failed: %w", err)
	}
	return strings.TrimSpace(string(output)), nil
}

// IsCommitAppliedOnBranch checks if a commit (or its cherry-picked equivalent) exists on a branch.
// First tries exact SHA match, then falls back to matching by commit subject line.
func IsCommitAppliedOnBranch(commitSHA, branchName string) bool {
	if CommitExistsOnBranch(commitSHA, branchName) {
		return true
	}

	subject, err := GetCommitMessage(commitSHA)
	if err != nil || subject == "" {
		return false
	}

	// List subject lines on the branch and compare exactly, avoiding false positives
	// from --grep matching inside commit bodies.
	cmd := exec.Command("git", "log", "--format=%s", branchName)
	output, err := cmd.Output()
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(output), "\n") {
		if line == subject {
			return true
		}
	}
	return false
}

// RunCherryPickContinue runs git cherry-pick --continue --no-edit
func RunCherryPickContinue() error {
	return RunCommandVerboseOnError("cherry-pick", "--continue", "--no-edit")
}

// CherryPickState holds the state needed to resume a cherry-pick operation
type CherryPickState struct {
	OriginalBranch    string   `json:"original_branch"`
	CommitSHAs        []string `json:"commit_shas"`
	CommitMessages    []string `json:"commit_messages"`
	Releases          []string `json:"releases"`
	CompletedReleases []string `json:"completed_releases,omitempty"`
	Stashed           bool     `json:"stashed"`
	NoVerify          bool     `json:"no_verify"`
	DryRun            bool     `json:"dry_run"`
	BranchSuffix      string   `json:"branch_suffix"`
	PRTitle           string   `json:"pr_title"`
}

const cherryPickStateFile = "ods-cherry-pick-state"

func stateFilePath() (string, error) {
	gitDir, err := GetGitDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(gitDir, cherryPickStateFile), nil
}

// SaveCherryPickState writes state to .git/ods-cherry-pick-state
func SaveCherryPickState(state *CherryPickState) error {
	path, err := stateFilePath()
	if err != nil {
		return fmt.Errorf("failed to determine state file path: %w", err)
	}

	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal state: %w", err)
	}

	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("failed to write state file: %w", err)
	}

	log.Debugf("Saved cherry-pick state to %s", path)
	return nil
}

// LoadCherryPickState reads state from .git/ods-cherry-pick-state
func LoadCherryPickState() (*CherryPickState, error) {
	path, err := stateFilePath()
	if err != nil {
		return nil, fmt.Errorf("failed to determine state file path: %w", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("no cherry-pick state file found at %s — did you start a cherry-pick with ods?", path)
		}
		return nil, fmt.Errorf("failed to read state file: %w", err)
	}

	var state CherryPickState
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, fmt.Errorf("failed to parse state file: %w", err)
	}

	log.Debugf("Loaded cherry-pick state from %s", path)
	return &state, nil
}

// CleanCherryPickState removes the state file
func CleanCherryPickState() {
	path, err := stateFilePath()
	if err != nil {
		log.Debugf("Failed to determine state file path for cleanup: %v", err)
		return
	}
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		log.Warnf("Failed to remove state file %s: %v", path, err)
	} else {
		log.Debugf("Cleaned up cherry-pick state file")
	}
}
