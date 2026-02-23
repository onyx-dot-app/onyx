package cmd

import (
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

// RunCIOptions holds options for the run-ci command
type RunCIOptions struct {
	DryRun bool
	Yes    bool
}

// NewRunCICommand creates a new run-ci command
func NewRunCICommand() *cobra.Command {
	opts := &RunCIOptions{}

	cmd := &cobra.Command{
		Use:   "run-ci <pr-number>",
		Short: "Create a branch and PR to run CI on a fork's PR",
		Long: `Create a branch and PR to run GitHub Actions CI on a fork's PR.

This command will:
  1. Fetch the PR information using the GitHub CLI
  2. Fetch the branch from the fork
  3. Create a new branch in the main repo (run-ci/<pr-number>)
  4. Push and create a PR that triggers CI
  5. Switch back to the original branch

This is useful for running CI on PRs from forks, which don't automatically
trigger GitHub Actions for security reasons.

Example usage:

	$ ods run-ci 7353`,
		Args: cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			runCI(cmd, args, opts)
		},
	}

	cmd.Flags().BoolVar(&opts.DryRun, "dry-run", false, "Perform all local operations but skip pushing to remote and creating PRs")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip confirmation prompts and automatically proceed")

	return cmd
}

// PRInfo holds information about a pull request
type PRInfo struct {
	Number         int    `json:"number"`
	Title          string `json:"title"`
	HeadRefName    string `json:"headRefName"`
	HeadRepository struct {
		Name string `json:"name"`
	} `json:"headRepository"`
	HeadRepositoryOwner struct {
		Login string `json:"login"`
	} `json:"headRepositoryOwner"`
	BaseRefName       string `json:"baseRefName"`
	IsCrossRepository bool   `json:"isCrossRepository"`
}

// ForkRepo returns the full fork repository path (owner/repo)
func (p *PRInfo) ForkRepo() string {
	if p.HeadRepositoryOwner.Login == "" || p.HeadRepository.Name == "" {
		return ""
	}
	return fmt.Sprintf("%s/%s", p.HeadRepositoryOwner.Login, p.HeadRepository.Name)
}

func runCI(cmd *cobra.Command, args []string, opts *RunCIOptions) {
	git.CheckGitHubCLI()

	prNumber := args[0]
	log.Debugf("Running CI for PR: %s", prNumber)

	if opts.DryRun {
		log.Warning("=== DRY RUN MODE: No remote operations will be performed ===")
	}

	// Save the current branch to switch back later
	originalBranch, err := git.GetCurrentBranch()
	if err != nil {
		log.Fatalf("Failed to get current branch: %v", err)
	}
	log.Debugf("Original branch: %s", originalBranch)

	// Get PR info using GitHub CLI
	prInfo, err := getPRInfo(prNumber)
	if err != nil {
		log.Fatalf("Failed to get PR info: %v", err)
	}

	forkRepo := prInfo.ForkRepo()
	log.Infof("PR #%d: %s", prInfo.Number, prInfo.Title)
	log.Infof("Fork: %s, Branch: %s", forkRepo, prInfo.HeadRefName)

	if !prInfo.IsCrossRepository {
		log.Fatalf("PR #%s is not from a fork - CI should already run automatically", prNumber)
	}

	// Confirm before proceeding
	if !opts.Yes {
		if !prompt.Confirm(fmt.Sprintf("Create CI branch for PR #%s? (yes/no): ", prNumber)) {
			log.Info("Exiting...")
			return
		}
	}

	// Create the CI branch
	ciBranch := fmt.Sprintf("run-ci/%s", prNumber)
	prTitle := fmt.Sprintf("chore: [Running GitHub actions for #%s]", prNumber)
	prBody := fmt.Sprintf("This PR runs GitHub Actions CI for #%s.\n\n- [x] Override Linear Check\n\n**This PR should be closed (not merged) after CI completes.**", prNumber)

	// Fetch the fork's branch
	if forkRepo == "" {
		log.Fatalf("Could not determine fork repository - headRepositoryOwner or headRepository.name is empty")
	}
	forkRemote := fmt.Sprintf("https://github.com/%s.git", forkRepo)
	log.Infof("Fetching branch %s from %s", prInfo.HeadRefName, forkRepo)
	if err := git.RunCommand("fetch", "--quiet", forkRemote, prInfo.HeadRefName); err != nil {
		log.Fatalf("Failed to fetch fork branch: %v", err)
	}

	// Create or update the CI branch from FETCH_HEAD
	if originalBranch == ciBranch {
		// Already on the CI branch - stash any uncommitted changes before resetting
		stashResult, err := git.StashChanges()
		if err != nil {
			log.Fatalf("Failed to stash changes: %v", err)
		}
		log.Infof("Already on %s, resetting to fork's HEAD", ciBranch)
		if err := git.RunCommand("reset", "--hard", "FETCH_HEAD"); err != nil {
			log.Fatalf("Failed to reset branch to fork's HEAD: %v", err)
		}
		git.RestoreStash(stashResult)
	} else {
		// Delete branch if it already exists locally (to ensure we're in sync with fork)
		if git.BranchExists(ciBranch) {
			log.Infof("Deleting existing local branch: %s", ciBranch)
			if err := git.RunCommand("branch", "-D", ciBranch); err != nil {
				log.Fatalf("Failed to delete existing branch: %v", err)
			}
		}
		log.Infof("Creating CI branch: %s", ciBranch)
		if err := git.RunCommand("checkout", "--quiet", "-b", ciBranch, "FETCH_HEAD"); err != nil {
			log.Fatalf("Failed to create CI branch: %v", err)
		}
	}

	if opts.DryRun {
		log.Warnf("[DRY RUN] Would push CI branch: %s", ciBranch)
		log.Warnf("[DRY RUN] Would create PR: %s", prTitle)
		// Switch back to original branch
		if err := git.RunCommand("switch", "--quiet", originalBranch); err != nil {
			log.Warnf("Failed to switch back to original branch: %v", err)
		}
		return
	}

	// Push the CI branch (force push in case it already exists)
	log.Infof("Pushing CI branch: %s", ciBranch)
	if err := git.RunCommand("push", "--quiet", "-f", "-u", "origin", ciBranch); err != nil {
		// Switch back to original branch before exiting
		if switchErr := git.RunCommand("switch", "--quiet", originalBranch); switchErr != nil {
			log.Warnf("Failed to switch back to original branch: %v", switchErr)
		}
		log.Fatalf("Failed to push CI branch: %v", err)
	}

	// Create PR using GitHub CLI
	log.Info("Creating PR...")
	prURL, err := createCIPR(ciBranch, prInfo.BaseRefName, prTitle, prBody)
	if err != nil {
		// Switch back to original branch before exiting
		if switchErr := git.RunCommand("switch", "--quiet", originalBranch); switchErr != nil {
			log.Warnf("Failed to switch back to original branch: %v", switchErr)
		}
		log.Fatalf("Failed to create PR: %v", err)
	}

	// Switch back to the original branch
	log.Infof("Switching back to original branch: %s", originalBranch)
	if err := git.RunCommand("switch", "--quiet", originalBranch); err != nil {
		log.Warnf("Failed to switch back to original branch: %v", err)
	}

	log.Infof("PR created successfully: %s", prURL)
	log.Info("Remember to close (not merge) this PR after CI completes!")
}

// getPRInfo fetches PR information using the GitHub CLI
func getPRInfo(prNumber string) (*PRInfo, error) {
	cmd := exec.Command("gh", "pr", "view", prNumber,
		"--json", "number,title,headRefName,headRepository,headRepositoryOwner,baseRefName,isCrossRepository")
	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("%w: %s", err, string(exitErr.Stderr))
		}
		return nil, err
	}

	var prInfo PRInfo
	if err := json.Unmarshal(output, &prInfo); err != nil {
		return nil, fmt.Errorf("failed to parse PR info: %w", err)
	}

	return &prInfo, nil
}

// createCIPR creates a pull request for CI using the GitHub CLI
func createCIPR(headBranch, baseBranch, title, body string) (string, error) {
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
