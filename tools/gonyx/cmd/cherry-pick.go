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

// CherryPickOptions holds options for the cherry-pick command
type CherryPickOptions struct {
	Releases []string
}

// NewCherryPickCommand creates a new cherry-pick command
func NewCherryPickCommand() *cobra.Command {
	opts := &CherryPickOptions{}

	cmd := &cobra.Command{
		Use:   "cherry-pick <commit-sha>",
		Short: "Cherry-pick a commit to a release branch",
		Long: `Cherry-pick a commit to a release branch and create a PR.

This command will:
  1. Find the nearest stable version tag (v*.*.* if --release not specified)
  2. Fetch the corresponding release branch (release/vMAJOR.MINOR)
  3. Create a hotfix branch with the cherry-picked commit
  4. Push and create a PR using the GitHub CLI
  5. Switch back to the original branch

The --release flag can be specified multiple times to cherry-pick to multiple release branches.`,
		Args: cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			runCherryPick(cmd, args, opts)
		},
	}

	cmd.Flags().StringSliceVar(&opts.Releases, "release", []string{}, "Release version(s) to cherry-pick to (e.g., v1.0, v1.1). Can be specified multiple times.")

	return cmd
}

func runCherryPick(cmd *cobra.Command, args []string, opts *CherryPickOptions) {
	commitSHA := args[0]
	log.Debugf("Cherry-picking commit: %s", commitSHA)

	// Save the current branch to switch back later
	originalBranch, err := getCurrentBranch()
	if err != nil {
		log.Fatalf("Failed to get current branch: %v", err)
	}
	log.Debugf("Original branch: %s", originalBranch)

	// Get the short SHA for branch naming
	shortSHA := commitSHA
	if len(shortSHA) > 8 {
		shortSHA = shortSHA[:8]
	}

	// Determine which releases to target
	var releases []string
	if len(opts.Releases) > 0 {
		releases = opts.Releases
		log.Infof("Using specified release versions: %v", releases)
	} else {
		// Find the nearest stable tag
		version, err := findNearestStableTag(commitSHA)
		if err != nil {
			log.Fatalf("Failed to find nearest stable tag: %v", err)
		}
		releases = []string{version}
		log.Infof("Auto-detected release version: %s", version)
	}

	// Get commit message for PR title
	commitMsg, err := getCommitMessage(commitSHA)
	if err != nil {
		log.Warnf("Failed to get commit message, using default title: %v", err)
		commitMsg = fmt.Sprintf("Hotfix: cherry-pick %s", shortSHA)
	}

	// Process each release
	prURLs := []string{}
	for _, release := range releases {
		log.Infof("\n--- Processing release %s ---", release)
		prURL, err := cherryPickToRelease(commitSHA, shortSHA, release, commitMsg, originalBranch)
		if err != nil {
			// Switch back to original branch before exiting on error
			runGitCommand("checkout", originalBranch)
			log.Fatalf("Failed to cherry-pick to release %s: %v", release, err)
		}
		prURLs = append(prURLs, prURL)
	}

	// Switch back to the original branch
	log.Infof("\nSwitching back to original branch: %s", originalBranch)
	if err := runGitCommand("checkout", originalBranch); err != nil {
		log.Warnf("Failed to switch back to original branch: %v", err)
	}

	// Print all PR URLs
	log.Info("\n=== Summary ===")
	for i, prURL := range prURLs {
		log.Infof("PR %d: %s", i+1, prURL)
	}
}

// cherryPickToRelease cherry-picks a commit to a specific release branch
func cherryPickToRelease(commitSHA, shortSHA, version, commitMsg, originalBranch string) (string, error) {
	releaseBranch := fmt.Sprintf("release/%s", version)
	hotfixBranch := fmt.Sprintf("hotfix/%s-%s", shortSHA, version)

	// Fetch the release branch
	log.Infof("Fetching release branch: %s", releaseBranch)
	if err := runGitCommand("fetch", "origin", releaseBranch); err != nil {
		return "", fmt.Errorf("failed to fetch release branch %s: %w", releaseBranch, err)
	}

	// Create the hotfix branch from the release branch
	log.Infof("Creating hotfix branch: %s", hotfixBranch)
	if err := runGitCommand("checkout", "-b", hotfixBranch, fmt.Sprintf("origin/%s", releaseBranch)); err != nil {
		return "", fmt.Errorf("failed to create hotfix branch: %w", err)
	}

	// Cherry-pick the commit
	log.Infof("Cherry-picking commit: %s", commitSHA)
	if err := runGitCommand("cherry-pick", commitSHA); err != nil {
		return "", fmt.Errorf("failed to cherry-pick commit: %w", err)
	}

	// Push the hotfix branch
	log.Infof("Pushing hotfix branch: %s", hotfixBranch)
	if err := runGitCommand("push", "-u", "origin", hotfixBranch); err != nil {
		return "", fmt.Errorf("failed to push hotfix branch: %w", err)
	}

	// Create PR using GitHub CLI
	log.Info("Creating PR...")
	prURL, err := createPR(hotfixBranch, releaseBranch, commitMsg, commitSHA)
	if err != nil {
		return "", fmt.Errorf("failed to create PR: %w", err)
	}

	log.Infof("PR created successfully: %s", prURL)
	return prURL, nil
}

// getCurrentBranch returns the name of the current git branch
func getCurrentBranch() (string, error) {
	cmd := exec.Command("git", "rev-parse", "--abbrev-ref", "HEAD")
	output, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("git rev-parse failed: %w", err)
	}
	return strings.TrimSpace(string(output)), nil
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
