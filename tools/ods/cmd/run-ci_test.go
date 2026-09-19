package cmd

// Command states for run-ci. The fork is a local bare repository that
// https://github.com/alice/onyx.git is rewritten to, so no test touches the
// network; gh is a fake that records its calls.
//
//	R1 fork PR, no CI PR yet                -> run-ci/7353 on origin at the
//	                                           fork head, exact PR args        TestRunCI_createsBranchAndPR
//	R2 CI PR exists, no --rerun             -> nothing fetched or pushed       TestRunCI_existingPRWithoutRerunDoesNothing
//	R3 --rerun while on the CI branch       -> reset to the fork head, stash
//	                                           restored, no new PR             TestRunCI_rerunOnCIBranchUpdatesExistingPR
//	R4 --dry-run with a stale local branch  -> branch recreated locally only   TestRunCI_dryRunRecreatesLocalBranchOnly
//	R5 --no-verify with a failing hook      -> push bypasses the hook          TestRunCI_noVerifySkipsPrePushHook
//	R6 gh, fork, or push failures           -> errors, back on the original    TestRunCI_failures

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

const (
	gitrelEditableBranch  = "chore/feature-pr-7353-edits"
	gitrelForkPRJSON      = `{"number":7353,"title":"feat: from a fork","body":"PR body","headRefName":"feature","headRepository":{"name":"onyx"},"headRepositoryOwner":{"login":"alice"},"baseRefName":"main","isCrossRepository":true}`
	gitrelPRViewArm       = `"pr view 7353 --json number,title,body,headRefName,headRepository,headRepositoryOwner,baseRefName,isCrossRepository") echo '` + gitrelForkPRJSON + `' ;;`
	gitrelNoCIPRArm       = `"pr list --head run-ci/7353 --state open --limit 1 --json url") echo '[]' ;;`
	gitrelCIPRArm         = `"pr list --head run-ci/7353 --state open --limit 1 --json url") echo '[{"url":"https://github.com/onyx-dot-app/onyx/pull/8000"}]' ;;`
	gitrelNoEditablePRArm = `"pr list --head ` + gitrelEditableBranch + ` --state all --limit 1 --json url") echo '[]' ;;`
	gitrelEditablePRArm   = `"pr list --head ` + gitrelEditableBranch + ` --state all --limit 1 --json url") echo '[{"url":"https://github.com/onyx-dot-app/onyx/pull/8001"}]' ;;`
	gitrelCIPRCreate      = `"pr create "*) echo https://github.com/onyx-dot-app/onyx/pull/9002 ;;`
)

type gitrelRunCIRepo struct {
	Origin  string
	Work    string
	ForkSHA string
}

// gitrelSetupRunCIRepo creates origin, a fork holding branch "feature", and a
// work clone on main that reaches the fork through a URL rewrite.
func gitrelSetupRunCIRepo(t *testing.T) gitrelRunCIRepo {
	t.Helper()
	origin, work := gittest.InitOriginAndWork(t)
	gitrelHooks(t, work, nil)
	base := gitrelCommit(t, work, "a.txt", "base\n", "chore: base")
	gittest.PublishMain(t, work)

	fork := t.TempDir()
	gittest.Git(t, fork, "init", "--quiet", "--bare")
	gittest.Git(t, work, "checkout", "--quiet", "-b", "feature", base)
	forkSHA := gitrelCommit(t, work, "feature.txt", "feature\n", "feat: from a fork")
	gittest.Git(t, work, "push", "--quiet", fork, "feature")
	gittest.Git(t, work, "checkout", "--quiet", "main")
	gittest.Git(t, work, "branch", "-D", "feature")

	gittest.Git(t, work, "config", "url."+fork+".insteadOf", "https://github.com/alice/onyx.git")
	// Refuse any transport but local paths, should the rewrite ever miss.
	t.Setenv("GIT_ALLOW_PROTOCOL", "file")
	t.Chdir(work)
	return gitrelRunCIRepo{Origin: origin, Work: work, ForkSHA: forkSHA}
}

func TestRunCI_createsBranchAndPR(t *testing.T) {
	// Precondition.
	repo := gitrelSetupRunCIRepo(t)
	calls := gitrelFakeGH(t, gitrelPRViewArm+"\n"+gitrelNoCIPRArm+"\n"+gitrelCIPRCreate)

	// Under test.
	err := runCI("7353", &RunCIOptions{Yes: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tip := gittest.Git(t, repo.Origin, "rev-parse", "refs/heads/run-ci/7353"); tip != repo.ForkSHA {
		t.Errorf("expected origin run-ci/7353 at the fork head %s, got %s", repo.ForkSHA, tip)
	}
	creates := gitrelCallsWithPrefix(calls(), "pr", "create")
	if len(creates) != 1 {
		t.Fatalf("expected one gh pr create call, got %q", creates)
	}
	gitrelAssertArgs(t, creates[0], []string{
		"pr", "create",
		"--base", "main",
		"--head", "run-ci/7353",
		"--title", "chore: [Running GitHub actions for #7353]",
		"--body", "This PR runs GitHub Actions CI for #7353.\n\n- [x] Override Linear Check\n\n**This PR should be closed (not merged) after CI completes.**",
	})
	if branch := gittest.Git(t, repo.Work, "branch", "--show-current"); branch != "main" {
		t.Errorf("expected to be back on main, got %q", branch)
	}
}

func TestRunCI_forEditsCreatesReplacementPR(t *testing.T) {
	repo := gitrelSetupRunCIRepo(t)
	calls := gitrelFakeGH(t, gitrelPRViewArm+"\n"+gitrelNoEditablePRArm+"\n"+gitrelCIPRCreate)

	err := runCI("7353", &RunCIOptions{Yes: true, ForEdits: true})

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tip := gittest.Git(t, repo.Origin, "rev-parse", "refs/heads/"+gitrelEditableBranch); tip != repo.ForkSHA {
		t.Errorf("expected origin %s at the fork head %s, got %s", gitrelEditableBranch, repo.ForkSHA, tip)
	}
	creates := gitrelCallsWithPrefix(calls(), "pr", "create")
	if len(creates) != 1 {
		t.Fatalf("expected one gh pr create call, got %q", creates)
	}
	gitrelAssertArgs(t, creates[0], []string{
		"pr", "create",
		"--base", "main",
		"--head", gitrelEditableBranch,
		"--title", "feat: from a fork [edit of #7353]",
		"--body", "> [!IMPORTANT]\n> This PR supersedes #7353. Merge this PR and close #7353 without merging.\n\n## Original PR description\n\nPR body\n\n- [ ] [Optional] Please cherry-pick this PR to the latest release version.\n- [x] Override Linear Check",
	})
}

func TestRunCI_forEditsRefusesExistingPR(t *testing.T) {
	repo := gitrelSetupRunCIRepo(t)
	gitrelFakeGH(t, gitrelPRViewArm+"\n"+gitrelEditablePRArm)

	err := runCI("7353", &RunCIOptions{Yes: true, ForEdits: true})

	want := "Cannot create editable PR: editable PR already exists for branch " +
		gitrelEditableBranch + ": https://github.com/onyx-dot-app/onyx/pull/8001"
	if err == nil || err.Error() != want {
		t.Fatalf("expected %q, got %v", want, err)
	}
	if gitrelRefExists(repo.Origin, "refs/heads/"+gitrelEditableBranch) {
		t.Error("existing editable PR must not replace the remote branch")
	}
}

func TestRunCI_forEditsRefusesExistingRemoteBranch(t *testing.T) {
	repo := gitrelSetupRunCIRepo(t)
	gitrelFakeGH(t, gitrelPRViewArm+"\n"+gitrelNoEditablePRArm)
	gittest.Git(t, repo.Work, "branch", gitrelEditableBranch)
	gittest.Git(t, repo.Work, "push", "--quiet", "origin", gitrelEditableBranch)

	err := runCI("7353", &RunCIOptions{Yes: true, ForEdits: true})

	want := "Cannot create editable PR: refusing to overwrite existing remote branch " +
		gitrelEditableBranch + "; delete it manually if it is safe to replace"
	if err == nil || err.Error() != want {
		t.Fatalf("expected %q, got %v", want, err)
	}
}

func TestRunCI_existingPRWithoutRerunDoesNothing(t *testing.T) {
	// Precondition.
	repo := gitrelSetupRunCIRepo(t)
	calls := gitrelFakeGH(t, gitrelPRViewArm+"\n"+gitrelCIPRArm)

	// Under test.
	err := runCI("7353", &RunCIOptions{Yes: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if gitrelRefExists(repo.Work, "refs/heads/run-ci/7353") || gitrelRefExists(repo.Origin, "refs/heads/run-ci/7353") {
		t.Error("expected no CI branch without --rerun")
	}
	if creates := gitrelCallsWithPrefix(calls(), "pr", "create"); len(creates) != 0 {
		t.Errorf("expected no PR, got %q", creates)
	}
}

func TestRunCI_rerunOnCIBranchUpdatesExistingPR(t *testing.T) {
	// Precondition: on a stale run-ci/7353 that origin also holds, with an
	// uncommitted change.
	repo := gitrelSetupRunCIRepo(t)
	calls := gitrelFakeGH(t, gitrelPRViewArm+"\n"+gitrelCIPRArm)
	gittest.Git(t, repo.Work, "checkout", "--quiet", "-b", "run-ci/7353")
	gittest.Git(t, repo.Work, "push", "--quiet", "origin", "run-ci/7353")
	if err := os.WriteFile(filepath.Join(repo.Work, "a.txt"), []byte("dirty\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	// Under test.
	err := runCI("7353", &RunCIOptions{Yes: true, Rerun: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tip := gittest.Git(t, repo.Origin, "rev-parse", "refs/heads/run-ci/7353"); tip != repo.ForkSHA {
		t.Errorf("expected origin run-ci/7353 force-updated to %s, got %s", repo.ForkSHA, tip)
	}
	if head := gittest.Git(t, repo.Work, "rev-parse", "HEAD"); head != repo.ForkSHA {
		t.Errorf("expected the local branch reset to %s, got %s", repo.ForkSHA, head)
	}
	if got := gitrelReadFile(t, repo.Work, "a.txt"); got != "dirty\n" {
		t.Errorf("expected the uncommitted change restored, got %q", got)
	}
	if creates := gitrelCallsWithPrefix(calls(), "pr", "create"); len(creates) != 0 {
		t.Errorf("expected the existing PR reused, got %q", creates)
	}
}

func TestRunCI_dryRunRecreatesLocalBranchOnly(t *testing.T) {
	// Precondition: a stale local run-ci/7353 at main, and no CI PR. --rerun
	// without a PR falls back to creating one.
	repo := gitrelSetupRunCIRepo(t)
	calls := gitrelFakeGH(t, gitrelPRViewArm+"\n"+gitrelNoCIPRArm)
	gittest.Git(t, repo.Work, "branch", "run-ci/7353")

	// Under test.
	err := runCI("7353", &RunCIOptions{Yes: true, DryRun: true, Rerun: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tip := gittest.Git(t, repo.Work, "rev-parse", "refs/heads/run-ci/7353"); tip != repo.ForkSHA {
		t.Errorf("expected the local branch recreated at %s, got %s", repo.ForkSHA, tip)
	}
	if gitrelRefExists(repo.Origin, "refs/heads/run-ci/7353") {
		t.Error("dry run must not push")
	}
	if creates := gitrelCallsWithPrefix(calls(), "pr", "create"); len(creates) != 0 {
		t.Errorf("dry run must not create a PR, got %q", creates)
	}
	if branch := gittest.Git(t, repo.Work, "branch", "--show-current"); branch != "main" {
		t.Errorf("expected to be back on main, got %q", branch)
	}
}

func TestRunCI_noVerifySkipsPrePushHook(t *testing.T) {
	// Precondition.
	repo := gitrelSetupRunCIRepo(t)
	gitrelFakeGH(t, gitrelPRViewArm+"\n"+gitrelNoCIPRArm+"\n"+gitrelCIPRCreate)
	gitrelHooks(t, repo.Work, map[string]string{"pre-push": "#!/bin/sh\nexit 1\n"})

	// Under test.
	err := runCI("7353", &RunCIOptions{Yes: true, NoVerify: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !gitrelRefExists(repo.Origin, "refs/heads/run-ci/7353") {
		t.Error("expected the push to bypass the failing hook")
	}
}

func TestRunCI_failsOutsideARepository(t *testing.T) {
	// Precondition.
	gitrelChdirOutsideRepo(t)
	calls := gitrelFakeGH(t, "")

	// Under test.
	err := runCI("7353", &RunCIOptions{Yes: true})

	// Postcondition: no PR is looked up.
	want := "Failed to get current branch: git branch failed: exit status 128"
	if err == nil || err.Error() != want {
		t.Fatalf("expected %q, got %v", want, err)
	}
	if views := gitrelCallsWithPrefix(calls(), "pr"); len(views) != 0 {
		t.Errorf("expected no gh pr calls, got %q", views)
	}
}

func TestRunCI_failures(t *testing.T) {
	cases := []struct {
		name    string
		ghArms  string
		setup   func(t *testing.T, repo gitrelRunCIRepo)
		wantErr string
	}{
		{
			name:    "PR lookup fails",
			ghArms:  `"pr view "*) echo 'no pull requests found' >&2; exit 1 ;;`,
			wantErr: "Failed to get PR info: exit status 1: no pull requests found",
		},
		{
			name:    "PR JSON unreadable",
			ghArms:  `"pr view "*) echo 'not json' ;;`,
			wantErr: "Failed to get PR info: failed to parse PR info",
		},
		{
			name:    "PR not from a fork",
			ghArms:  `"pr view "*) echo '{"number":7353,"isCrossRepository":false}' ;;`,
			wantErr: "PR #7353 is not from a fork - CI should already run automatically",
		},
		{
			name:    "CI PR lookup fails",
			ghArms:  gitrelPRViewArm + "\n" + `"pr list "*) echo 'rate limited' >&2; exit 1 ;;`,
			wantErr: "Failed to check for existing CI PR: exit status 1: rate limited",
		},
		{
			name:    "CI PR list unreadable",
			ghArms:  gitrelPRViewArm + "\n" + `"pr list "*) echo '{}' ;;`,
			wantErr: "Failed to check for existing CI PR: failed to parse PR list",
		},
		{
			name:    "fork owner unknown",
			ghArms:  `"pr view "*) echo '{"number":7353,"headRefName":"feature","isCrossRepository":true}' ;;` + "\n" + gitrelNoCIPRArm,
			wantErr: "Could not determine fork repository - headRepositoryOwner or headRepository.name is empty",
		},
		{
			name:    "fork branch missing",
			ghArms:  `"pr view "*) echo '{"number":7353,"headRefName":"gone","headRepository":{"name":"onyx"},"headRepositoryOwner":{"login":"alice"},"isCrossRepository":true}' ;;` + "\n" + gitrelNoCIPRArm,
			wantErr: "Failed to fetch fork branch: exit status 1",
		},
		{
			name:   "push rejected",
			ghArms: gitrelPRViewArm + "\n" + gitrelNoCIPRArm,
			setup: func(t *testing.T, repo gitrelRunCIRepo) {
				gittest.RejectPushes(t, repo.Origin)
			},
			wantErr: "Failed to push CI branch: exit status 1",
		},
		{
			name:    "PR creation fails",
			ghArms:  gitrelPRViewArm + "\n" + gitrelNoCIPRArm + "\n" + `"pr create "*) echo 'base branch not found' >&2; exit 1 ;;`,
			wantErr: "Failed to create PR: exit status 1: base branch not found",
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			// Precondition.
			repo := gitrelSetupRunCIRepo(t)
			gitrelFakeGH(t, c.ghArms)
			if c.setup != nil {
				c.setup(t, repo)
			}

			// Under test.
			err := runCI("7353", &RunCIOptions{Yes: true})

			// Postcondition.
			if err == nil || !strings.HasPrefix(err.Error(), c.wantErr) {
				t.Fatalf("expected an error starting with %q, got %v", c.wantErr, err)
			}
			if branch := gittest.Git(t, repo.Work, "branch", "--show-current"); branch != "main" {
				t.Errorf("expected to stay on or return to main, got %q", branch)
			}
		})
	}
}
