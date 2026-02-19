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
	NoVerify bool
	Continue bool
}

// NewCherryPickCommand creates a new cherry-pick command
func NewCherryPickCommand() *cobra.Command {
	opts := &CherryPickOptions{}

	cmd := &cobra.Command{
		Use:     "cherry-pick <commit-sha> [<commit-sha>...]",
		Aliases: []string{"cp"},
		Short:   "Cherry-pick one or more commits to a release branch",
		Long: `Cherry-pick one or more commits to a release branch and create a PR.

This command will:
  1. Find the nearest stable version tag
  2. Fetch the corresponding release branch(es)
  3. Create a hotfix branch with the cherry-picked commit(s)
  4. Push and create a PR using the GitHub CLI
  5. Switch back to the original branch

Multiple commits will be cherry-picked in the order specified, similar to git cherry-pick.
The --release flag can be specified multiple times to cherry-pick to multiple release branches.

If a cherry-pick hits a merge conflict, resolve it manually, then run:
  $ ods cherry-pick --continue

Example usage:

	$ ods cherry-pick foo123 bar456 --release 2.5 --release 2.6
	$ ods cp foo123 --release 2.5`,
		Args: func(cmd *cobra.Command, args []string) error {
			cont, _ := cmd.Flags().GetBool("continue")
			if cont {
				if len(args) > 0 {
					return fmt.Errorf("--continue does not accept positional arguments")
				}
				return nil
			}
			if len(args) < 1 {
				return fmt.Errorf("requires at least 1 arg(s), only received %d", len(args))
			}
			return nil
		},
		Run: func(cmd *cobra.Command, args []string) {
			if opts.Continue {
				runCherryPickContinue()
			} else {
				runCherryPick(cmd, args, opts)
			}
		},
	}

	cmd.Flags().BoolVar(&opts.Continue, "continue", false, "Resume a cherry-pick after manual conflict resolution")
	cmd.Flags().StringSliceVar(&opts.Releases, "release", []string{}, "Release version(s) to cherry-pick to (e.g., 1.0, v1.1). 'v' prefix is optional. Can be specified multiple times.")
	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Perform all local operations but skip pushing to remote and creating PRs")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip confirmation prompts and automatically proceed")
	cmd.Flags().BoolVar(&opts.NoVerify, "no-verify", false, "Skip pre-commit and commit-msg hooks for cherry-pick and push")

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

	// Stash any uncommitted changes before switching branches
	stashResult, err := git.StashChanges()
	if err != nil {
		log.Fatalf("Failed to stash changes: %v", err)
	}

	// Fetch commits from remote before cherry-picking
	if err := git.FetchCommits(commitSHAs); err != nil {
		log.Warnf("Failed to fetch commits: %v", err)
	}

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
			git.RestoreStash(stashResult)
			log.Fatalf("Failed to find nearest stable tag: %v", err)
		}

		// Prompt user for confirmation
		if !opts.Yes {
			if !prompt.Confirm(fmt.Sprintf("Auto-detected release version: %s. Continue? (yes/no): ", version)) {
				log.Info("If you want to cherry-pick to a different release, use the --release flag. Exiting...")
				git.RestoreStash(stashResult)
				return
			}
		} else {
			log.Infof("Auto-detected release version: %s", version)
		}

		releases = []string{version}
	}

	// Get commit messages for PR title and body
	commitMessages := make([]string, len(commitSHAs))
	for i, sha := range commitSHAs {
		msg, err := git.GetCommitMessage(sha)
		if err != nil {
			log.Warnf("Failed to get commit message for %s: %v", sha, err)
			commitMessages[i] = ""
		} else {
			commitMessages[i] = msg
		}
	}

	var prTitle string
	if len(commitSHAs) == 1 {
		if commitMessages[0] != "" {
			prTitle = commitMessages[0]
		} else {
			shortSHA := commitSHAs[0]
			if len(shortSHA) > 8 {
				shortSHA = shortSHA[:8]
			}
			prTitle = fmt.Sprintf("chore(hotfix): cherry-pick %s", shortSHA)
		}
	} else {
		// For multiple commits, use a generic title
		prTitle = fmt.Sprintf("chore(hotfix): cherry-pick %d commits", len(commitSHAs))
	}

	// Save state so --continue can resume if a conflict occurs
	state := &git.CherryPickState{
		OriginalBranch: originalBranch,
		CommitSHAs:     commitSHAs,
		CommitMessages: commitMessages,
		Releases:       releases,
		Stashed:        stashResult.Stashed,
		NoVerify:       opts.NoVerify,
		DryRun:         opts.DryRun,
		BranchSuffix:   branchSuffix,
		PRTitle:        prTitle,
	}
	if err := git.SaveCherryPickState(state); err != nil {
		log.Warnf("Failed to save cherry-pick state (--continue won't work): %v", err)
	}

	finishCherryPick(state, stashResult)
}

// finishCherryPick processes each release (cherry-pick remaining commits, push, create PR),
// then switches back to the original branch and cleans up.
func finishCherryPick(state *git.CherryPickState, stashResult *git.StashResult) {
	completed := make(map[string]bool, len(state.CompletedReleases))
	for _, r := range state.CompletedReleases {
		completed[r] = true
	}

	prURLs := []string{}
	for _, release := range state.Releases {
		if completed[release] {
			log.Infof("Release %s already completed, skipping", release)
			continue
		}

		log.Infof("Processing release %s", release)
		prTitleWithRelease := fmt.Sprintf("%s to release %s", state.PRTitle, release)
		prURL, err := cherryPickToRelease(state.CommitSHAs, state.CommitMessages, state.BranchSuffix, release, prTitleWithRelease, state.DryRun, state.NoVerify)
		if err != nil {
			if strings.Contains(err.Error(), "merge conflict") {
				if stashResult.Stashed {
					log.Warn("Your uncommitted changes are still stashed.")
					log.Infof("After resolving the conflict and returning to %s, run: git stash pop", state.OriginalBranch)
				}
			} else {
				if switchErr := git.RunCommand("switch", "--quiet", state.OriginalBranch); switchErr != nil {
					log.Warnf("Failed to switch back to original branch: %v", switchErr)
				}
				git.RestoreStash(stashResult)
			}
			log.Fatalf("Failed to cherry-pick to release %s: %v", release, err)
		}

		// Mark release as completed and persist so --continue skips it
		state.CompletedReleases = append(state.CompletedReleases, release)
		if saveErr := git.SaveCherryPickState(state); saveErr != nil {
			log.Warnf("Failed to update state file: %v", saveErr)
		}

		if prURL != "" {
			prURLs = append(prURLs, prURL)
		}
	}

	log.Infof("Switching back to original branch: %s", state.OriginalBranch)
	if err := git.RunCommand("switch", "--quiet", state.OriginalBranch); err != nil {
		log.Warnf("Failed to switch back to original branch: %v", err)
	}

	git.RestoreStash(stashResult)
	git.CleanCherryPickState()

	for i, prURL := range prURLs {
		log.Infof("PR %d: %s", i+1, prURL)
	}
}

// runCherryPickContinue resumes a cherry-pick after manual conflict resolution.
// It finishes any in-progress git cherry-pick, then falls into the normal
// cherryPickToRelease path which handles skip-applied-commits, push, and PR creation.
func runCherryPickContinue() {
	git.CheckGitHubCLI()

	state, err := git.LoadCherryPickState()
	if err != nil {
		log.Fatalf("Cannot continue: %v", err)
	}

	log.Infof("Resuming cherry-pick (original branch: %s, releases: %v)", state.OriginalBranch, state.Releases)

	// If git cherry-pick is still in progress (CHERRY_PICK_HEAD exists), continue it
	if git.IsCherryPickInProgress() {
		log.Info("Continuing in-progress cherry-pick...")
		if err := git.RunCherryPickContinue(); err != nil {
			log.Fatalf("git cherry-pick --continue failed: %v", err)
		}
	}

	// Re-use the normal per-release flow: cherryPickToRelease already handles
	// "branch exists → skip applied commits → push → create PR"
	stashResult := &git.StashResult{Stashed: state.Stashed}
	finishCherryPick(state, stashResult)
}

// cherryPickToRelease cherry-picks one or more commits to a specific release branch
func cherryPickToRelease(commitSHAs, commitMessages []string, branchSuffix, version, prTitle string, dryRun, noVerify bool) (string, error) {
	releaseBranch := fmt.Sprintf("release/%s", version)
	hotfixBranch := fmt.Sprintf("hotfix/%s-%s", branchSuffix, version)

	// Fetch the release branch
	log.Infof("Fetching release branch: %s", releaseBranch)
	if err := git.RunCommand("fetch", "--prune", "--quiet", "origin", releaseBranch); err != nil {
		return "", fmt.Errorf("failed to fetch release branch %s: %w", releaseBranch, err)
	}

	// Check if hotfix branch already exists
	branchExists := git.BranchExists(hotfixBranch)
	if branchExists {
		log.Infof("Hotfix branch %s already exists, switching", hotfixBranch)
		if err := git.RunCommand("switch", "--quiet", hotfixBranch); err != nil {
			return "", fmt.Errorf("failed to checkout existing hotfix branch: %w", err)
		}

		// Check which commits need to be cherry-picked
		commitsToCherry := []string{}
		for _, sha := range commitSHAs {
			if git.IsCommitAppliedOnBranch(sha, hotfixBranch) {
				log.Infof("Commit %s already applied on branch %s, skipping", sha, hotfixBranch)
			} else {
				commitsToCherry = append(commitsToCherry, sha)
			}
		}

		if len(commitsToCherry) == 0 {
			log.Infof("All commits already exist on branch %s", hotfixBranch)
		} else {
			// Cherry-pick only the missing commits
			if err := performCherryPick(commitsToCherry); err != nil {
				return "", err
			}
		}
	} else {
		// Create the hotfix branch from the release branch
		log.Infof("Creating hotfix branch: %s", hotfixBranch)
		if err := git.RunCommand("checkout", "--quiet", "-b", hotfixBranch, fmt.Sprintf("origin/%s", releaseBranch)); err != nil {
			return "", fmt.Errorf("failed to create hotfix branch: %w", err)
		}

		// Cherry-pick all commits
		if err := performCherryPick(commitSHAs); err != nil {
			return "", err
		}
	}

	if dryRun {
		log.Warnf("[DRY RUN] Would push hotfix branch: %s", hotfixBranch)
		log.Warnf("[DRY RUN] Would create PR from %s to %s", hotfixBranch, releaseBranch)
		return "", nil
	}

	// Push the hotfix branch
	log.Infof("Pushing hotfix branch: %s", hotfixBranch)
	pushArgs := []string{"push", "-u", "origin", hotfixBranch}
	if noVerify {
		pushArgs = []string{"push", "--no-verify", "-u", "origin", hotfixBranch}
	}
	if err := git.RunCommandVerboseOnError(pushArgs...); err != nil {
		return "", fmt.Errorf("failed to push hotfix branch: %w", err)
	}

	// Create PR using GitHub CLI
	log.Info("Creating PR...")
	prURL, err := createCherryPickPR(hotfixBranch, releaseBranch, prTitle, commitSHAs, commitMessages)
	if err != nil {
		return "", fmt.Errorf("failed to create PR: %w", err)
	}

	log.Infof("PR created successfully: %s", prURL)
	return prURL, nil
}

// performCherryPick cherry-picks the given commits
func performCherryPick(commitSHAs []string) error {
	if len(commitSHAs) == 0 {
		return nil
	}

	if len(commitSHAs) == 1 {
		log.Infof("Cherry-picking commit: %s", commitSHAs[0])
	} else {
		log.Infof("Cherry-picking %d commits: %s", len(commitSHAs), strings.Join(commitSHAs, " "))
	}

	// Build git cherry-pick command with all commits
	// Note: git cherry-pick does not support --no-verify; hooks run during cherry-pick
	cherryPickArgs := []string{"cherry-pick"}
	cherryPickArgs = append(cherryPickArgs, commitSHAs...)

	if err := git.RunCommandVerboseOnError(cherryPickArgs...); err != nil {
		// Check if this is a merge conflict
		if git.HasMergeConflict() {
			log.Error("Cherry-pick failed due to merge conflict!")
			log.Info("To resolve:")
			log.Info("  1. Fix the conflicts in the affected files")
			log.Info("  2. Stage the resolved files: git add <files>")
			log.Info("  3. Continue: ods cherry-pick --continue")
			return fmt.Errorf("merge conflict during cherry-pick")
		}
		// Check if cherry-pick is empty (commit already applied with different SHA)
		// Only skip if there are no staged changes - if user resolved conflicts and staged,
		// they should run `git cherry-pick --continue` instead
		if git.IsCherryPickInProgress() {
			if git.HasStagedChanges() {
				log.Error("Cherry-pick in progress with staged changes.")
				log.Info("It looks like you resolved conflicts. Run: git cherry-pick --continue")
				return fmt.Errorf("cherry-pick in progress with staged changes")
			}
			log.Info("Cherry-pick is empty (changes already applied), skipping...")
			if skipErr := git.RunCommand("cherry-pick", "--skip"); skipErr != nil {
				return fmt.Errorf("failed to skip empty cherry-pick: %w", skipErr)
			}
			return nil
		}
		return fmt.Errorf("failed to cherry-pick commits: %w", err)
	}
	return nil
}

// normalizeVersion ensures the version has a 'v' prefix
func normalizeVersion(version string) string {
	if !strings.HasPrefix(version, "v") {
		return "v" + version
	}
	return version
}

// extractPRNumbers extracts GitHub PR numbers (e.g., #1234) from a commit message
func extractPRNumbers(commitMsg string) []string {
	re := regexp.MustCompile(`#(\d+)`)
	matches := re.FindAllString(commitMsg, -1)
	return matches
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
func createCherryPickPR(headBranch, baseBranch, title string, commitSHAs, commitMessages []string) (string, error) {
	var body string

	// Collect all original PR numbers for the summary
	allPRNumbers := []string{}
	for _, msg := range commitMessages {
		if msg != "" {
			prNumbers := extractPRNumbers(msg)
			allPRNumbers = append(allPRNumbers, prNumbers...)
		}
	}

	if len(commitSHAs) == 1 {
		body = fmt.Sprintf("Cherry-pick of commit %s to %s branch.", commitSHAs[0], baseBranch)
		if len(allPRNumbers) > 0 {
			body += fmt.Sprintf("\n\nOriginal PR: %s", strings.Join(allPRNumbers, ", "))
		}
	} else {
		body = fmt.Sprintf("Cherry-pick of %d commits to %s branch:\n\n", len(commitSHAs), baseBranch)
		for i, sha := range commitSHAs {
			// Include original PR reference if present
			var prRef string
			if i < len(commitMessages) && commitMessages[i] != "" {
				prNumbers := extractPRNumbers(commitMessages[i])
				if len(prNumbers) > 0 {
					prRef = fmt.Sprintf(" (Original: %s)", strings.Join(prNumbers, ", "))
				}
			}
			body += fmt.Sprintf("- %s%s\n", sha, prRef)
		}
	}

	// Add standard checklist
	body += "\n\n"
	body += "- [x] [Required] I have considered whether this PR needs to be cherry-picked to the latest beta branch.\n"
	body += "- [x] [Optional] Override Linear Check\n"

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
