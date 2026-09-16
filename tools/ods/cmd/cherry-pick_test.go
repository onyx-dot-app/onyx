package cmd

// Command states for cherry-pick. The fixture's origin holds main and
// release/v2.5 cut before FixSHA; gh is a fake that records its calls.
//
//	C1 one commit, explicit --release, dirty tree -> hotfix branch on origin,
//	                                                 exact gh pr create args,
//	                                                 tree and branch restored     TestCherryPick_opensPRForExplicitRelease
//	C2 two commits, auto-detected release, flags  -> first-last branch, generic
//	                                                 title, flag assignees win    TestCherryPick_autoDetectsReleaseForTwoCommits
//	C3 --dry-run                                  -> local hotfix branch only     TestCherryPick_dryRunKeepsEverythingLocal
//	C4 re-run after a dry run                     -> branch reused, no duplicate  TestCherryPick_rerunReusesHotfixBranch
//	C5 untouched hotfix branch, release moved     -> rebased onto the new tip     TestCherryPick_rebasesUntouchedHotfixBranch
//	C6 change already on the release branch       -> empty pick skipped           TestCherryPick_skipsEmptyCherryPick
//	C7 merge conflict, then --continue            -> state kept, then finished    TestCherryPick_conflictThenContinueFinishes
//	C8 failures before or during the pick         -> original branch and stash
//	                                                 restored                     TestCherryPick_failuresRestoreBranchAndStash
//	C9 failing pre-push hook                      -> --no-verify skips it         TestCherryPick_noVerifySkipsPrePushHook
//	C10 --continue with a completed release       -> only the rest is processed   TestCherryPickContinue_skipsCompletedReleases
//	C11 --continue without state or mid-rebase    -> refused                      TestCherryPickContinue_refusals
//	C12 resolved conflict staged, plain re-run    -> refuses to skip it           TestPerformCherryPick_keepsStagedResolution
//	D1 --dispatch with PR number and SHA          -> one workflow run each        TestCherryPickDispatch_triggersWorkflowPerCommit
//	D2 --dispatch --dry-run                       -> no workflow run              TestCherryPickDispatch_dryRunDispatchesNothing
//	D3 --dispatch failures                        -> errors name the input        TestCherryPickDispatch_failures

import (
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

const gitrelPRCreateArm = `"pr create "*) echo https://github.com/onyx-dot-app/onyx/pull/9001 ;;`

type gitrelCherryPickRepo struct {
	Origin string
	Work   string
	// BaseSHA is the release/v2.5 cut point.
	BaseSHA string
	// FixSHA is on main only and adds fix.txt.
	FixSHA string
}

// gitrelSetupCherryPickRepo creates origin with main and release/v2.5 cut
// before a fix commit, and makes the work clone the current directory.
func gitrelSetupCherryPickRepo(t *testing.T) gitrelCherryPickRepo {
	t.Helper()
	origin, work := gittest.InitOriginAndWork(t)
	gitrelHooks(t, work, nil)
	base := gitrelCommit(t, work, "a.txt", "base\n", "chore: base")
	fix := gitrelCommit(t, work, "fix.txt", "fixed\n", "fix: repair the widget (#123)")
	gittest.PublishMain(t, work)
	gittest.PublishReleaseBranch(t, work, "release/v2.5", base)
	t.Chdir(work)
	return gitrelCherryPickRepo{Origin: origin, Work: work, BaseSHA: base, FixSHA: fix}
}

// gitrelPushReleaseCommit adds a commit on top of parent and publishes it as
// origin's release/v2.5, leaving the work clone on main.
func gitrelPushReleaseCommit(t *testing.T, work, parent, filename, content, msg string) string {
	t.Helper()
	gittest.Git(t, work, "checkout", "--quiet", "-b", "gitrel-tmp", parent)
	sha := gitrelCommit(t, work, filename, content, msg)
	gittest.Git(t, work, "push", "--quiet", "--force", "origin", "gitrel-tmp:refs/heads/release/v2.5")
	gittest.Git(t, work, "checkout", "--quiet", "main")
	gittest.Git(t, work, "branch", "-D", "gitrel-tmp")
	return sha
}

func gitrelStatePath(work string) string {
	return filepath.Join(work, ".git", "ods-cherry-pick-state")
}

func gitrelAssertBackOnMainAndClean(t *testing.T, work string) {
	t.Helper()
	if branch := gittest.Git(t, work, "branch", "--show-current"); branch != "main" {
		t.Errorf("expected to be back on main, got %q", branch)
	}
	if _, err := os.Stat(gitrelStatePath(work)); !os.IsNotExist(err) {
		t.Errorf("expected the state file to be removed, stat returned %v", err)
	}
}

func TestCherryPick_opensPRForExplicitRelease(t *testing.T) {
	// Precondition: an uncommitted change must survive the branch switches.
	repo := gitrelSetupCherryPickRepo(t)
	calls := gitrelFakeGH(t, gitrelPRCreateArm)
	t.Setenv("CHERRY_PICK_ASSIGNEE", " alice,bob,alice")
	if err := os.WriteFile(filepath.Join(repo.Work, "a.txt"), []byte("dirty\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	// Under test: "2.5" gains its v prefix.
	err := runCherryPick(NewCherryPickCommand(), []string{repo.FixSHA}, &CherryPickOptions{Releases: []string{"2.5"}})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	hotfix := "hotfix/" + repo.FixSHA[:8] + "-v2.5"
	if parent := gittest.Git(t, repo.Origin, "rev-parse", hotfix+"^"); parent != repo.BaseSHA {
		t.Errorf("expected %s on origin to sit on the release tip %s, got parent %s", hotfix, repo.BaseSHA, parent)
	}
	if subject := gittest.Git(t, repo.Origin, "log", "-1", "--format=%s", hotfix); subject != "fix: repair the widget (#123)" {
		t.Errorf("expected the cherry-picked subject, got %q", subject)
	}
	creates := gitrelCallsWithPrefix(calls(), "pr", "create")
	if len(creates) != 1 {
		t.Fatalf("expected one gh pr create call, got %d", len(creates))
	}
	gitrelAssertArgs(t, creates[0], []string{
		"pr", "create",
		"--base", "release/v2.5",
		"--head", hotfix,
		"--title", "fix: repair the widget (#123) to release v2.5",
		"--body", "Cherry-pick of commit " + repo.FixSHA + " to release/v2.5 branch.\n\nOriginal PR: #123\n\n- [x] [Optional] Override Linear Check\n",
		"--label", "cherry-pick 🍒",
		"--assignee", "alice",
		"--assignee", "bob",
	})
	gitrelAssertBackOnMainAndClean(t, repo.Work)
	if got := gitrelReadFile(t, repo.Work, "a.txt"); got != "dirty\n" {
		t.Errorf("expected the uncommitted change restored, got %q", got)
	}
	if stashes := gittest.Git(t, repo.Work, "stash", "list"); stashes != "" {
		t.Errorf("expected the stash to be popped, got %q", stashes)
	}
}

func TestCherryPick_autoDetectsReleaseForTwoCommits(t *testing.T) {
	// Precondition: a second commit without a PR reference.
	repo := gitrelSetupCherryPickRepo(t)
	tidySHA := gitrelCommit(t, repo.Work, "tidy.txt", "tidy\n", "chore: tidy")
	gittest.PublishMain(t, repo.Work)
	calls := gitrelFakeGH(t, gitrelPRCreateArm)
	// --assignee overrides the environment.
	t.Setenv("CHERRY_PICK_ASSIGNEE", "ignored")

	// Under test.
	cmd := NewCherryPickCommand()
	cmd.SetArgs([]string{repo.FixSHA, tidySHA, "--yes", "--assignee", "carol", "--assignee", "carol,dave"})
	cmd.SetOut(io.Discard)
	cmd.SetErr(io.Discard)
	err := cmd.Execute()

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	hotfix := "hotfix/" + repo.FixSHA[:8] + "-" + tidySHA[:8] + "-v2.5"
	if count := gittest.Git(t, repo.Origin, "rev-list", "--count", "release/v2.5.."+hotfix); count != "2" {
		t.Errorf("expected 2 commits on %s past the release, got %s", hotfix, count)
	}
	creates := gitrelCallsWithPrefix(calls(), "pr", "create")
	if len(creates) != 1 {
		t.Fatalf("expected one gh pr create call, got %d", len(creates))
	}
	gitrelAssertArgs(t, creates[0], []string{
		"pr", "create",
		"--base", "release/v2.5",
		"--head", hotfix,
		"--title", "chore(hotfix): cherry-pick 2 commits to release v2.5",
		"--body", "Cherry-pick of 2 commits to release/v2.5 branch:\n\n- " + repo.FixSHA + " (Original: #123)\n- " + tidySHA + "\n\n\n- [x] [Optional] Override Linear Check\n",
		"--label", "cherry-pick 🍒",
		"--assignee", "carol",
		"--assignee", "dave",
	})
	gitrelAssertBackOnMainAndClean(t, repo.Work)
}

func TestCherryPick_dryRunKeepsEverythingLocal(t *testing.T) {
	// Precondition.
	repo := gitrelSetupCherryPickRepo(t)
	calls := gitrelFakeGH(t, gitrelPRCreateArm)

	// Under test.
	err := runCherryPick(NewCherryPickCommand(), []string{repo.FixSHA}, &CherryPickOptions{Releases: []string{"v2.5"}, DryRun: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	hotfix := "hotfix/" + repo.FixSHA[:8] + "-v2.5"
	if subject := gittest.Git(t, repo.Work, "log", "-1", "--format=%s", hotfix); subject != "fix: repair the widget (#123)" {
		t.Errorf("expected the local hotfix branch to hold the fix, got %q", subject)
	}
	if gitrelRefExists(repo.Origin, "refs/heads/"+hotfix) {
		t.Error("dry run must not push the hotfix branch")
	}
	if creates := gitrelCallsWithPrefix(calls(), "pr", "create"); len(creates) != 0 {
		t.Errorf("dry run must not create a PR, got %q", creates)
	}
	gitrelAssertBackOnMainAndClean(t, repo.Work)
}

func TestCherryPick_rerunReusesHotfixBranch(t *testing.T) {
	// Precondition: a dry run left the hotfix branch with the fix applied.
	repo := gitrelSetupCherryPickRepo(t)
	calls := gitrelFakeGH(t, gitrelPRCreateArm)
	opts := &CherryPickOptions{Releases: []string{"2.5"}, DryRun: true}
	if err := runCherryPick(NewCherryPickCommand(), []string{repo.FixSHA}, opts); err != nil {
		t.Fatalf("dry run failed: %v", err)
	}
	hotfix := "hotfix/" + repo.FixSHA[:8] + "-v2.5"
	dryRunTip := gittest.Git(t, repo.Work, "rev-parse", hotfix)

	// Under test.
	opts.DryRun = false
	err := runCherryPick(NewCherryPickCommand(), []string{repo.FixSHA}, opts)

	// Postcondition: the branch is pushed as it was, not picked a second time.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tip := gittest.Git(t, repo.Origin, "rev-parse", hotfix); tip != dryRunTip {
		t.Errorf("expected origin %s at the dry-run tip %s, got %s", hotfix, dryRunTip, tip)
	}
	if creates := gitrelCallsWithPrefix(calls(), "pr", "create"); len(creates) != 1 {
		t.Errorf("expected one gh pr create call, got %d", len(creates))
	}
	gitrelAssertBackOnMainAndClean(t, repo.Work)
}

func TestCherryPick_rebasesUntouchedHotfixBranch(t *testing.T) {
	// Precondition: a hotfix branch with no commits of its own, and a release
	// branch that moved on origin since it was created.
	repo := gitrelSetupCherryPickRepo(t)
	calls := gitrelFakeGH(t, gitrelPRCreateArm)
	hotfix := "hotfix/" + repo.FixSHA[:8] + "-v2.5"
	gittest.Git(t, repo.Work, "branch", hotfix, repo.BaseSHA)
	newTip := gitrelPushReleaseCommit(t, repo.Work, repo.BaseSHA, "r.txt", "release\n", "chore: release-only change")

	// Under test.
	err := runCherryPick(NewCherryPickCommand(), []string{repo.FixSHA}, &CherryPickOptions{Releases: []string{"2.5"}})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if parent := gittest.Git(t, repo.Origin, "rev-parse", hotfix+"^"); parent != newTip {
		t.Errorf("expected %s rebased onto the new release tip %s, got parent %s", hotfix, newTip, parent)
	}
	if creates := gitrelCallsWithPrefix(calls(), "pr", "create"); len(creates) != 1 {
		t.Errorf("expected one gh pr create call, got %d", len(creates))
	}
	gitrelAssertBackOnMainAndClean(t, repo.Work)
}

func TestCherryPick_skipsEmptyCherryPick(t *testing.T) {
	// Precondition: the release branch already holds the fix under another
	// subject, so the pick applies no change.
	repo := gitrelSetupCherryPickRepo(t)
	gitrelFakeGH(t, gitrelPRCreateArm)
	releaseTip := gitrelPushReleaseCommit(t, repo.Work, repo.BaseSHA, "fix.txt", "fixed\n", "fix: backported by hand")

	// Under test.
	err := runCherryPick(NewCherryPickCommand(), []string{repo.FixSHA}, &CherryPickOptions{Releases: []string{"2.5"}})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	hotfix := "hotfix/" + repo.FixSHA[:8] + "-v2.5"
	if tip := gittest.Git(t, repo.Origin, "rev-parse", hotfix); tip != releaseTip {
		t.Errorf("expected %s at the release tip %s after skipping, got %s", hotfix, releaseTip, tip)
	}
	if gitrelRefExists(repo.Work, "CHERRY_PICK_HEAD") {
		t.Error("expected the empty cherry-pick to be skipped")
	}
	gitrelAssertBackOnMainAndClean(t, repo.Work)
}

func TestCherryPick_conflictThenContinueFinishes(t *testing.T) {
	// Precondition: main and the release branch change a.txt differently.
	repo := gitrelSetupCherryPickRepo(t)
	calls := gitrelFakeGH(t, gitrelPRCreateArm)
	conflictSHA := gitrelCommit(t, repo.Work, "a.txt", "main\n", "fix: change a (#77)")
	gittest.PublishMain(t, repo.Work)
	gitrelPushReleaseCommit(t, repo.Work, repo.BaseSHA, "a.txt", "release\n", "chore: release change")
	hotfix := "hotfix/" + conflictSHA[:8] + "-v2.5"

	// Under test: the first run stops at the conflict.
	err := runCherryPick(NewCherryPickCommand(), []string{conflictSHA}, &CherryPickOptions{Releases: []string{"2.5"}})

	// Postcondition: the user is left on the hotfix branch with state saved.
	if err == nil || err.Error() != "Failed to cherry-pick to release v2.5: merge conflict during cherry-pick" {
		t.Fatalf("expected a merge conflict error, got %v", err)
	}
	if branch := gittest.Git(t, repo.Work, "branch", "--show-current"); branch != hotfix {
		t.Errorf("expected to stay on %s to resolve the conflict, got %q", hotfix, branch)
	}
	state, err := git.LoadCherryPickState()
	if err != nil {
		t.Fatalf("expected a saved state, got %v", err)
	}
	if state.OriginalBranch != "main" || state.PRTitle != "fix: change a (#77)" || len(state.CompletedReleases) != 0 {
		t.Errorf("unexpected state: %+v", state)
	}

	// Under test: resolve, stage, and continue.
	if err := os.WriteFile(filepath.Join(repo.Work, "a.txt"), []byte("resolved\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	gittest.Git(t, repo.Work, "add", "a.txt")
	err = runCherryPickContinue()

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error from --continue: %v", err)
	}
	if content := gittest.Git(t, repo.Origin, "show", hotfix+":a.txt"); content != "resolved" {
		t.Errorf("expected the resolution on origin, got %q", content)
	}
	if subject := gittest.Git(t, repo.Origin, "log", "-1", "--format=%s", hotfix); subject != "fix: change a (#77)" {
		t.Errorf("expected the original subject kept, got %q", subject)
	}
	creates := gitrelCallsWithPrefix(calls(), "pr", "create")
	if len(creates) != 1 || creates[0][7] != "fix: change a (#77) to release v2.5" {
		t.Errorf("expected one PR titled from the saved state, got %q", creates)
	}
	gitrelAssertBackOnMainAndClean(t, repo.Work)
}

func TestCherryPick_failuresRestoreBranchAndStash(t *testing.T) {
	cases := []struct {
		name    string
		ghArms  string
		setup   func(t *testing.T, repo gitrelCherryPickRepo)
		args    func(repo gitrelCherryPickRepo) []string
		opts    CherryPickOptions
		wantErr string
	}{
		{
			name:    "release branch missing on origin",
			args:    func(repo gitrelCherryPickRepo) []string { return []string{repo.FixSHA} },
			opts:    CherryPickOptions{Releases: []string{"9.9"}},
			wantErr: "Failed to cherry-pick to release v9.9: failed to fetch release branch release/v9.9",
		},
		{
			name:    "unknown commit",
			args:    func(gitrelCherryPickRepo) []string { return []string{"0123456789abcdef0123456789abcdef01234567"} },
			opts:    CherryPickOptions{Releases: []string{"2.5"}},
			wantErr: "Failed to cherry-pick to release v2.5: failed to cherry-pick commits",
		},
		{
			name:    "gh pr create fails",
			ghArms:  `"pr create "*) echo 'GraphQL: no permission' >&2; exit 1 ;;`,
			args:    func(repo gitrelCherryPickRepo) []string { return []string{repo.FixSHA} },
			opts:    CherryPickOptions{Releases: []string{"2.5"}},
			wantErr: "Failed to cherry-pick to release v2.5: failed to create PR: exit status 1: GraphQL: no permission",
		},
		{
			name: "malformed assignee environment",
			setup: func(t *testing.T, _ gitrelCherryPickRepo) {
				t.Setenv("CHERRY_PICK_ASSIGNEE", `"alice`)
			},
			args:    func(repo gitrelCherryPickRepo) []string { return []string{repo.FixSHA} },
			opts:    CherryPickOptions{Releases: []string{"2.5"}},
			wantErr: "Failed to parse assignees: failed to parse CHERRY_PICK_ASSIGNEE=",
		},
		{
			name: "no release branch to auto-detect",
			setup: func(t *testing.T, repo gitrelCherryPickRepo) {
				gittest.Git(t, repo.Work, "push", "--quiet", "origin", "--delete", "release/v2.5")
			},
			args:    func(repo gitrelCherryPickRepo) []string { return []string{repo.FixSHA} },
			opts:    CherryPickOptions{Yes: true},
			wantErr: "Failed to auto-detect the target release (pass --release explicitly): no release/vX.Y branches found on origin",
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			// Precondition.
			repo := gitrelSetupCherryPickRepo(t)
			gitrelFakeGH(t, c.ghArms)
			if c.setup != nil {
				c.setup(t, repo)
			}
			if err := os.WriteFile(filepath.Join(repo.Work, "a.txt"), []byte("dirty\n"), 0o644); err != nil {
				t.Fatal(err)
			}

			// Under test.
			opts := c.opts
			err := runCherryPick(NewCherryPickCommand(), c.args(repo), &opts)

			// Postcondition.
			if err == nil || !strings.HasPrefix(err.Error(), c.wantErr) {
				t.Fatalf("expected an error starting with %q, got %v", c.wantErr, err)
			}
			if branch := gittest.Git(t, repo.Work, "branch", "--show-current"); branch != "main" {
				t.Errorf("expected to be back on main, got %q", branch)
			}
			if got := gitrelReadFile(t, repo.Work, "a.txt"); got != "dirty\n" {
				t.Errorf("expected the uncommitted change restored, got %q", got)
			}
		})
	}
}

func TestCherryPick_noVerifySkipsPrePushHook(t *testing.T) {
	cases := []struct {
		name     string
		noVerify bool
		wantErr  string
	}{
		{name: "hooks run by default", wantErr: "Failed to cherry-pick to release v2.5: failed to push hotfix branch"},
		{name: "--no-verify skips them", noVerify: true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			// Precondition.
			repo := gitrelSetupCherryPickRepo(t)
			calls := gitrelFakeGH(t, gitrelPRCreateArm)
			gitrelHooks(t, repo.Work, map[string]string{"pre-push": "#!/bin/sh\necho 'pre-push hook refused'\nexit 1\n"})

			// Under test.
			err := runCherryPick(NewCherryPickCommand(), []string{repo.FixSHA}, &CherryPickOptions{Releases: []string{"2.5"}, NoVerify: c.noVerify})

			// Postcondition.
			hotfix := "refs/heads/hotfix/" + repo.FixSHA[:8] + "-v2.5"
			if c.wantErr != "" {
				if err == nil || !strings.HasPrefix(err.Error(), c.wantErr) || !strings.Contains(err.Error(), "pre-push hook refused") {
					t.Fatalf("expected %q with the hook output, got %v", c.wantErr, err)
				}
				if gitrelRefExists(repo.Origin, hotfix) {
					t.Error("the hook must have blocked the push")
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if !gitrelRefExists(repo.Origin, hotfix) {
				t.Error("expected the push to bypass the hook")
			}
			if creates := gitrelCallsWithPrefix(calls(), "pr", "create"); len(creates) != 1 {
				t.Errorf("expected one gh pr create call, got %d", len(creates))
			}
		})
	}
}

func TestCherryPickContinue_skipsCompletedReleases(t *testing.T) {
	// Precondition: v2.4 is recorded as done. It does not exist on origin, so
	// processing it again would fail.
	repo := gitrelSetupCherryPickRepo(t)
	calls := gitrelFakeGH(t, gitrelPRCreateArm)
	state := &git.CherryPickState{
		OriginalBranch:    "main",
		CommitSHAs:        []string{repo.FixSHA},
		CommitMessages:    []string{"fix: repair the widget (#123)"},
		Releases:          []string{"v2.4", "v2.5"},
		CompletedReleases: []string{"v2.4"},
		BranchSuffix:      repo.FixSHA[:8],
		PRTitle:           "fix: repair the widget (#123)",
	}
	if err := git.SaveCherryPickState(state); err != nil {
		t.Fatal(err)
	}

	// Under test.
	err := runCherryPickContinue()

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	creates := gitrelCallsWithPrefix(calls(), "pr", "create")
	if len(creates) != 1 || creates[0][3] != "release/v2.5" {
		t.Errorf("expected a single PR against release/v2.5, got %q", creates)
	}
	gitrelAssertBackOnMainAndClean(t, repo.Work)
}

func TestCherryPickContinue_refusals(t *testing.T) {
	t.Run("no saved state", func(t *testing.T) {
		gitrelSetupCherryPickRepo(t)
		gitrelFakeGH(t, "")

		err := runCherryPickContinue()

		if err == nil || !strings.HasPrefix(err.Error(), "Cannot continue: no cherry-pick state file found") {
			t.Errorf("expected a missing-state error, got %v", err)
		}
	})

	t.Run("rebase in progress", func(t *testing.T) {
		repo := gitrelSetupCherryPickRepo(t)
		calls := gitrelFakeGH(t, gitrelPRCreateArm)
		if err := git.SaveCherryPickState(&git.CherryPickState{OriginalBranch: "main", Releases: []string{"v2.5"}}); err != nil {
			t.Fatal(err)
		}
		gittest.Git(t, repo.Work, "update-ref", "REBASE_HEAD", repo.FixSHA)

		err := runCherryPickContinue()

		if err == nil || !strings.HasPrefix(err.Error(), "A git rebase is in progress. Resolve it first:") {
			t.Errorf("expected a rebase-in-progress error, got %v", err)
		}
		if creates := gitrelCallsWithPrefix(calls(), "pr", "create"); len(creates) != 0 {
			t.Errorf("expected no PR, got %q", creates)
		}
		if _, err := os.Stat(gitrelStatePath(repo.Work)); err != nil {
			t.Errorf("expected the state kept for a later --continue, got %v", err)
		}
	})
}

func TestPerformCherryPick_keepsStagedResolution(t *testing.T) {
	// Precondition: a conflicted cherry-pick whose resolution is staged but not
	// yet committed.
	repo := gitrelSetupCherryPickRepo(t)
	gittest.Git(t, repo.Work, "checkout", "--quiet", "-b", "topic", repo.BaseSHA)
	topicSHA := gitrelCommit(t, repo.Work, "a.txt", "topic\n", "feat: topic")
	gittest.Git(t, repo.Work, "checkout", "--quiet", "main")
	gitrelCommit(t, repo.Work, "a.txt", "main\n", "feat: main")
	conflict := exec.Command("git", "cherry-pick", topicSHA)
	conflict.Dir = repo.Work
	if err := conflict.Run(); err == nil {
		t.Fatal("expected the setup cherry-pick to conflict")
	}
	if err := os.WriteFile(filepath.Join(repo.Work, "a.txt"), []byte("resolved\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	gittest.Git(t, repo.Work, "add", "a.txt")

	// Under test.
	err := performCherryPick([]string{repo.FixSHA})

	// Postcondition: the resolution is neither skipped nor lost.
	if err == nil || err.Error() != "cherry-pick in progress with staged changes" {
		t.Fatalf("expected a staged-changes error, got %v", err)
	}
	if !gitrelRefExists(repo.Work, "CHERRY_PICK_HEAD") {
		t.Error("expected the cherry-pick to stay in progress")
	}
	if staged := gittest.Git(t, repo.Work, "show", ":a.txt"); staged != "resolved" {
		t.Errorf("expected the staged resolution kept, got %q", staged)
	}
}

func TestCherryPickDispatch_triggersWorkflowPerCommit(t *testing.T) {
	// Precondition: "123" is a PR number; a six-digit number is a SHA. The API
	// resolves the first SHA to PR 456 and knows no PR for the second.
	calls := gitrelFakeGH(t, `"pr view 123 --json mergeCommit --jq .mergeCommit.oid") echo 1111111111111111111111111111111111111111 ;;
"api repos/{owner}/{repo}/commits/abcdef1/pulls --jq .[0].number") echo 456 ;;
"api "*) echo 'Not Found' >&2; exit 1 ;;`)

	// Under test.
	err := runCherryPickDispatch([]string{"123", "abcdef1", "123456"}, &CherryPickOptions{Releases: []string{"v2.5"}})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	runs := gitrelCallsWithPrefix(calls(), "workflow", "run")
	if len(runs) != 3 {
		t.Fatalf("expected 3 workflow runs, got %q", runs)
	}
	gitrelAssertArgs(t, runs[0], []string{"workflow", "run", "post-merge-beta-cherry-pick.yml", "-f", "merge_commit_sha=1111111111111111111111111111111111111111", "-f", "pr_number=123", "-f", "release=v2.5"})
	gitrelAssertArgs(t, runs[1], []string{"workflow", "run", "post-merge-beta-cherry-pick.yml", "-f", "merge_commit_sha=abcdef1", "-f", "pr_number=456", "-f", "release=v2.5"})
	gitrelAssertArgs(t, runs[2], []string{"workflow", "run", "post-merge-beta-cherry-pick.yml", "-f", "merge_commit_sha=123456", "-f", "release=v2.5"})
	if views := gitrelCallsWithPrefix(calls(), "pr", "view"); len(views) != 1 {
		t.Errorf("expected only 123 resolved as a PR, got %q", views)
	}
}

func TestCherryPickDispatch_dryRunDispatchesNothing(t *testing.T) {
	// Precondition.
	calls := gitrelFakeGH(t, `"api "*) echo 789 ;;`)

	// Under test: no --release lets the workflow auto-detect.
	err := runCherryPickDispatch([]string{"abcdef1"}, &CherryPickOptions{DryRun: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if runs := gitrelCallsWithPrefix(calls(), "workflow"); len(runs) != 0 {
		t.Errorf("dry run must not dispatch, got %q", runs)
	}
}

func TestCherryPickDispatch_failures(t *testing.T) {
	cases := []struct {
		name     string
		ghArms   string
		args     []string
		releases []string
		wantErr  string
	}{
		{
			name:     "more than one release",
			args:     []string{"abcdef1"},
			releases: []string{"v2.4", "v2.5"},
			wantErr:  "--dispatch supports at most one --release",
		},
		{
			name:    "unmerged PR",
			ghArms:  `"pr view "*) echo null ;;`,
			args:    []string{"123"},
			wantErr: "Failed to resolve PR #123: PR #123 has no merge commit (is it merged?)",
		},
		{
			name:    "workflow dispatch rejected",
			ghArms:  `"pr view "*) echo 2222222222222222222222222222222222222222 ;; "workflow run "*) echo 'HTTP 422: Workflow does not have workflow_dispatch trigger'; exit 1 ;;`,
			args:    []string{"123"},
			wantErr: "Failed to dispatch cherry-pick workflow for PR #123: exit status 1: HTTP 422: Workflow does not have workflow_dispatch trigger",
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			gitrelFakeGH(t, c.ghArms)

			err := runCherryPickDispatch(c.args, &CherryPickOptions{Releases: c.releases})

			if err == nil || err.Error() != c.wantErr {
				t.Errorf("expected %q, got %v", c.wantErr, err)
			}
		})
	}
}

func TestCherryPick_failsOutsideARepository(t *testing.T) {
	// Precondition.
	gitrelChdirOutsideRepo(t)
	calls := gitrelFakeGH(t, "")

	// Under test.
	err := runCherryPick(NewCherryPickCommand(), []string{"0123456789abcdef0123456789abcdef01234567"}, &CherryPickOptions{Releases: []string{"2.5"}, Yes: true})

	// Postcondition: no PR is created.
	want := "Failed to get current branch: git branch failed: exit status 128"
	if err == nil || err.Error() != want {
		t.Fatalf("expected %q, got %v", want, err)
	}
	if prs := gitrelCallsWithPrefix(calls(), "pr"); len(prs) != 0 {
		t.Errorf("expected no gh pr calls, got %q", prs)
	}
}
