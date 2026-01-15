package cmd

import (
	"fmt"
	"os/exec"
	"regexp"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

// CherryPickOptions holds options for the cherry-pick command
type CherryPickOptions struct {
	Releases []string
	DryRun   bool
	Yes      bool
}

// NewCherryPickCommand creates a new cherry-pick command
func NewCherryPickCommand() *cobra.Command {
	opts := &CherryPickOptions{}

	cmd := &cobra.Command{
		Use:   "cherry-pick <commit-sha> [<commit-sha>...]",
		Short: "Cherry-pick one or more commits to a release branch",
		Long: `Cherry-pick one or more commits to a release branch and create a PR.

This command will:
  1. Find the nearest stable version tag
  2. Fetch the corresponding release branch(es)
  3. Create a hotfix branch with the cherry-picked commit(s)
  4. Push and create a PR using the GitHub CLI
  5. Switch back to the original branch

Multiple commits will be cherry-picked in the order specified, similar to git cherry-pick.
The --release flag can be specified multiple times to cherry-pick to multiple release branches.
Example usage:

	$ ods cherry-pick foo123 bar456 --release 2.5 --release 2.6`,
		Args: cobra.MinimumNArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			runCherryPick(cmd, args, opts)
		},
	}

	cmd.Flags().StringSliceVar(&opts.Releases, "release", []string{}, "Release version(s) to cherry-pick to (e.g., 1.0, v1.1). 'v' prefix is optional. Can be specified multiple times.")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Perform all local operations but skip pushing to remote and creating PRs")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip confirmation prompts and automatically proceed")

	return cmd
}

func runCherryPick(cmd *cobra.Command, args []string, opts *CherryPickOptions) {
	git.CheckGitHubCLI()

	commitSHAs := args
	if len(commitSHAs) == 1 {
		log.Debugf("Cherry-picking commit: %s", commitSHAs[0])
	} else {
		log.Debugf("Cherry-picking %d commits: %s", len(commitSHAs), strings.Join(commitSHAs, ", "))
	}

	if opts.DryRun {
		log.Warning("=== DRY RUN MODE: No remote operations will be performed ===")
	}

	// Save the current branch to switch back later
	originalBranch, err := git.GetCurrentBranch()
	if err != nil {
		log.Fatalf("Failed to get current branch: %v", err)
	}
	log.Debugf("Original branch: %s", originalBranch)

	// Get the short SHA(s) for branch naming
	var branchSuffix string
	if len(commitSHAs) == 1 {
		shortSHA := commitSHAs[0]
		if len(shortSHA) > 8 {
			shortSHA = shortSHA[:8]
		}
		branchSuffix = shortSHA
	} else {
		// For multiple commits, use first-last notation
		firstSHA := commitSHAs[0]
		lastSHA := commitSHAs[len(commitSHAs)-1]
		if len(firstSHA) > 8 {
			firstSHA = firstSHA[:8]
		}
		if len(lastSHA) > 8 {
			lastSHA = lastSHA[:8]
		}
		branchSuffix = fmt.Sprintf("%s-%s", firstSHA, lastSHA)
	}

	// Determine which releases to target
	var releases []string
	if len(opts.Releases) > 0 {
		// Normalize versions to ensure they have 'v' prefix
		for _, rel := range opts.Releases {
			releases = append(releases, normalizeVersion(rel))
		}
		log.Debugf("Using specified release versions: %v", releases)
	} else {
		// Find the nearest stable tag using the first commit
		version, err := findNearestStableTag(commitSHAs[0])
		if err != nil {
			log.Fatalf("Failed to find nearest stable tag: %v", err)
		}

		// Prompt user for confirmation
		if !opts.Yes {
			if !prompt.Confirm(fmt.Sprintf("Auto-detected release version: %s. Continue? (yes/no): ", version)) {
				log.Info("If you want to cherry-pick to a different release, use the --release flag. Exiting...")
				return
			}
		} else {
			log.Infof("Auto-detected release version: %s", version)
		}

		releases = []string{version}
	}

	// Get commit message(s) for PR title
	var prTitle string
	if len(commitSHAs) == 1 {
		commitMsg, err := git.GetCommitMessage(commitSHAs[0])
		if err != nil {
			log.Warnf("Failed to get commit message, using default title: %v", err)
			shortSHA := commitSHAs[0]
			if len(shortSHA) > 8 {
				shortSHA = shortSHA[:8]
			}
			prTitle = fmt.Sprintf("chore(hotfix): cherry-pick %s", shortSHA)
		} else {
			prTitle = commitMsg
		}
	} else {
		// For multiple commits, use a generic title
		prTitle = fmt.Sprintf("chore(hotfix): cherry-pick %d commits", len(commitSHAs))
	}

	// Process each release
	prURLs := []string{}
	for _, release := range releases {
		log.Infof("Processing release %s", release)
		prTitleWithRelease := fmt.Sprintf("%s to release %s", prTitle, release)
		prURL, err := cherryPickToRelease(commitSHAs, branchSuffix, release, prTitleWithRelease, opts.DryRun)
		if err != nil {
			// Switch back to original branch before exiting on error
			if switchErr := git.RunCommand("switch", "--quiet", originalBranch); switchErr != nil {
				log.Warnf("Failed to switch back to original branch: %v", switchErr)
			}
			log.Fatalf("Failed to cherry-pick to release %s: %v", release, err)
		}
		if prURL != "" {
			prURLs = append(prURLs, prURL)
		}
	}

	// Switch back to the original branch
	log.Infof("Switching back to original branch: %s", originalBranch)
	if err := git.RunCommand("switch", "--quiet", originalBranch); err != nil {
		log.Warnf("Failed to switch back to original branch: %v", err)
	}

	// Print all PR URLs
	for i, prURL := range prURLs {
		log.Infof("PR %d: %s", i+1, prURL)
	}
}

// cherryPickToRelease cherry-picks one or more commits to a specific release branch
func cherryPickToRelease(commitSHAs []string, branchSuffix, version, prTitle string, dryRun bool) (string, error) {
	releaseBranch := fmt.Sprintf("release/%s", version)
	hotfixBranch := fmt.Sprintf("hotfix/%s-%s", branchSuffix, version)

	// Fetch the release branch
	log.Infof("Fetching release branch: %s", releaseBranch)
	if err := git.RunCommand("fetch", "--prune", "--quiet", "origin", releaseBranch); err != nil {
		return "", fmt.Errorf("failed to fetch release branch %s: %w", releaseBranch, err)
	}

	// Create the hotfix branch from the release branch
	log.Infof("Creating hotfix branch: %s", hotfixBranch)
	if err := git.RunCommand("checkout", "--quiet", "-b", hotfixBranch, fmt.Sprintf("origin/%s", releaseBranch)); err != nil {
		return "", fmt.Errorf("failed to create hotfix branch: %w", err)
	}

	// Cherry-pick the commits
	if len(commitSHAs) == 1 {
		log.Infof("Cherry-picking commit: %s", commitSHAs[0])
	} else {
		log.Infof("Cherry-picking %d commits: %s", len(commitSHAs), strings.Join(commitSHAs, " "))
	}

	// Build git cherry-pick command with all commits
	cherryPickArgs := append([]string{"cherry-pick"}, commitSHAs...)
	if err := git.RunCommand(cherryPickArgs...); err != nil {
		return "", fmt.Errorf("failed to cherry-pick commits: %w", err)
	}

	if dryRun {
		log.Warnf("[DRY RUN] Would push hotfix branch: %s", hotfixBranch)
		log.Warnf("[DRY RUN] Would create PR from %s to %s", hotfixBranch, releaseBranch)
		return "", nil
	}

	// Push the hotfix branch
	log.Infof("Pushing hotfix branch: %s", hotfixBranch)
	if err := git.RunCommand("push", "--quiet", "-u", "origin", hotfixBranch); err != nil {
		return "", fmt.Errorf("failed to push hotfix branch: %w", err)
	}

	// Create PR using GitHub CLI
	log.Info("Creating PR...")
	prURL, err := createCherryPickPR(hotfixBranch, releaseBranch, prTitle, commitSHAs)
	if err != nil {
		return "", fmt.Errorf("failed to create PR: %w", err)
	}

	log.Infof("PR created successfully: %s", prURL)
	return prURL, nil
}

// normalizeVersion ensures the version has a 'v' prefix
func normalizeVersion(version string) string {
	if !strings.HasPrefix(version, "v") {
		return "v" + version
	}
	return version
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

// createCherryPickPR creates a pull request for cherry-picks using the GitHub CLI
func createCherryPickPR(headBranch, baseBranch, title string, commitSHAs []string) (string, error) {
	var body string
	if len(commitSHAs) == 1 {
		body = fmt.Sprintf("Cherry-pick of commit %s to %s branch.", commitSHAs[0], baseBranch)
	} else {
		body = fmt.Sprintf("Cherry-pick of %d commits to %s branch:\n\n", len(commitSHAs), baseBranch)
		for _, sha := range commitSHAs {
			body += fmt.Sprintf("- %s\n", sha)
		}
	}

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
