package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
)

// NewCherryPickCommand creates a new cherry-pick command
func NewCherryPickCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "cherry-pick <commit-sha>",
		Short: "Cherry-pick a commit to a release branch",
		Long: `Cherry-pick a commit to a release branch and create a PR.

This command will:
  1. Find the nearest stable version tag (v*.*.*)
  2. Fetch the corresponding release branch (release/vMAJOR.MINOR)
  3. Create a hotfix branch with the cherry-picked commit
  4. Push and create a PR using the GitHub CLI`,
		Args: cobra.ExactArgs(1),
		Run:  runCherryPick,
	}

	return cmd
}

func runCherryPick(cmd *cobra.Command, args []string) {
	commitSHA := args[0]
	log.Debugf("Cherry-picking commit: %s", commitSHA)

	// Get the short SHA for branch naming
	shortSHA := commitSHA
	if len(shortSHA) > 8 {
		shortSHA = shortSHA[:8]
	}

	// Find the nearest stable tag
	version, err := findNearestStableTag(commitSHA)
	if err != nil {
		log.Fatalf("Failed to find nearest stable tag: %v", err)
	}
	log.Infof("Found nearest stable version: %s", version)

	releaseBranch := fmt.Sprintf("release/%s", version)
	hotfixBranch := fmt.Sprintf("hotfix/%s", shortSHA)

	// Fetch the release branch
	log.Infof("Fetching release branch: %s", releaseBranch)
	if err := runGitCommand("fetch", "origin", releaseBranch); err != nil {
		log.Fatalf("Failed to fetch release branch %s: %v", releaseBranch, err)
	}

	// Create the hotfix branch from the release branch
	log.Infof("Creating hotfix branch: %s", hotfixBranch)
	if err := runGitCommand("checkout", "-b", hotfixBranch, fmt.Sprintf("origin/%s", releaseBranch)); err != nil {
		log.Fatalf("Failed to create hotfix branch: %v", err)
	}

	// Cherry-pick the commit
	log.Infof("Cherry-picking commit: %s", commitSHA)
	if err := runGitCommand("cherry-pick", commitSHA); err != nil {
		log.Fatalf("Failed to cherry-pick commit: %v", err)
	}

	// Push the hotfix branch
	log.Infof("Pushing hotfix branch: %s", hotfixBranch)
	if err := runGitCommand("push", "-u", "origin", hotfixBranch); err != nil {
		log.Fatalf("Failed to push hotfix branch: %v", err)
	}

	// Get commit message for PR title
	commitMsg, err := getCommitMessage(commitSHA)
	if err != nil {
		log.Warnf("Failed to get commit message, using default title: %v", err)
		commitMsg = fmt.Sprintf("Hotfix: cherry-pick %s", shortSHA)
	}

	// Create PR using GitHub CLI
	log.Info("Creating PR...")
	prURL, err := createPR(hotfixBranch, releaseBranch, commitMsg, commitSHA)
	if err != nil {
		log.Fatalf("Failed to create PR: %v", err)
	}

	log.Infof("PR created successfully: %s", prURL)
}

// findNearestStableTag finds the nearest tag matching v*.*.* pattern and returns major.minor
func findNearestStableTag(commitSHA string) (string, error) {
	// Get tags that are ancestors of the commit, sorted by version
	cmd := exec.Command("git", "describe", "--tags", "--abbrev=0", "--match", "v*.*.*", commitSHA)
	output, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("git describe failed: %w", err)
	}

	tag := strings.TrimSpace(string(output))
	log.Debugf("Found tag: %s", tag)

	// Extract major.minor with v prefix from tag (e.g., v1.2.3 -> v1.2)
	re := regexp.MustCompile(`^(v\d+\.\d+)\.\d+`)
	matches := re.FindStringSubmatch(tag)
	if len(matches) < 2 {
		return "", fmt.Errorf("tag %s does not match expected format v*.*.* ", tag)
	}

	return matches[1], nil
}

// runGitCommand executes a git command and returns any error
func runGitCommand(args ...string) error {
	log.Debugf("Running: git %s", strings.Join(args, " "))
	cmd := exec.Command("git", args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

// getCommitMessage gets the first line of a commit message
func getCommitMessage(commitSHA string) (string, error) {
	cmd := exec.Command("git", "log", "-1", "--format=%s", commitSHA)
	output, err := cmd.Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(output)), nil
}

// createPR creates a pull request using the GitHub CLI
func createPR(headBranch, baseBranch, title, commitSHA string) (string, error) {
	body := fmt.Sprintf("Cherry-pick of commit %s to %s branch.", commitSHA, baseBranch)

	cmd := exec.Command("gh", "pr", "create",
		"--base", baseBranch,
		"--head", headBranch,
		"--title", title,
		"--body", body,
	)

	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return "", fmt.Errorf("%w: %s", err, string(exitErr.Stderr))
		}
		return "", err
	}

	prURL := strings.TrimSpace(string(output))
	return prURL, nil
}
