package git

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// gitrelChdirOutsideRepo makes an empty directory the working directory and
// stops git from finding a repository above it.
func gitrelChdirOutsideRepo(t *testing.T) {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(dir))
	t.Chdir(dir)
}

// gitrelHooks points the repository at dir to a fresh hooks directory holding
// the given hook scripts, so a global core.hooksPath cannot interfere.
func gitrelHooks(t *testing.T, dir string, hooks map[string]string) {
	t.Helper()
	hookDir := t.TempDir()
	for name, script := range hooks {
		if err := os.WriteFile(filepath.Join(hookDir, name), []byte(script), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	gittest.Git(t, dir, "config", "core.hooksPath", hookDir)
}

// gitrelWarnings collects warning messages from the standard logger until the
// test ends.
type gitrelWarnings chan string

func (w gitrelWarnings) Levels() []log.Level { return []log.Level{log.WarnLevel} }

func (w gitrelWarnings) Fire(e *log.Entry) error {
	w <- e.Message
	return nil
}

func gitrelCaptureWarnings(t *testing.T) gitrelWarnings {
	t.Helper()
	w := make(gitrelWarnings, 10)
	logger := log.StandardLogger()
	original := logger.ReplaceHooks(log.LevelHooks{})
	logger.AddHook(w)
	t.Cleanup(func() { logger.ReplaceHooks(original) })
	return w
}

// gitrelDebugToStdout sets the debug level and returns a function that stops
// capturing stdout and returns what was written.
func gitrelDebugToStdout(t *testing.T) func() string {
	t.Helper()
	level := log.GetLevel()
	log.SetLevel(log.DebugLevel)
	originalOut := log.StandardLogger().Out
	log.SetOutput(io.Discard)
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	original := os.Stdout
	os.Stdout = w
	restore := func() {
		os.Stdout = original
		log.SetLevel(level)
		log.SetOutput(originalOut)
	}
	t.Cleanup(func() {
		restore()
		_ = w.Close()
		_ = r.Close()
	})
	return func() string {
		restore()
		_ = w.Close()
		data, _ := io.ReadAll(r)
		return string(data)
	}
}

func TestHintAfter(t *testing.T) {
	t.Run("slow function logs the hint and returns its error", func(t *testing.T) {
		// Precondition.
		warnings := gitrelCaptureWarnings(t)
		wantErr := os.ErrDeadlineExceeded

		// Under test: the function returns only once the hint is logged.
		err := HintAfter(time.Millisecond, "use --fast", func() error {
			select {
			case msg := <-warnings:
				if msg != "use --fast" {
					t.Errorf("expected hint %q, got %q", "use --fast", msg)
				}
			case <-time.After(5 * time.Second):
				t.Error("expected the hint while the function ran")
			}
			return wantErr
		})

		// Postcondition.
		if err != wantErr {
			t.Errorf("expected %v, got %v", wantErr, err)
		}
	})

	t.Run("fast function stops the timer", func(t *testing.T) {
		// Precondition.
		warnings := gitrelCaptureWarnings(t)

		// Under test.
		err := HintAfter(20*time.Millisecond, "use --fast", func() error { return nil })

		// Postcondition.
		if err != nil {
			t.Errorf("unexpected error: %v", err)
		}
		select {
		case msg := <-warnings:
			t.Errorf("expected no hint after the function returned, got %q", msg)
		case <-time.After(100 * time.Millisecond):
		}
	})
}

func TestGetCurrentBranch(t *testing.T) {
	// Precondition.
	repo := newTestRepo(t)
	repo.Git("checkout", "--quiet", "-b", "feature/x")

	// Under test and postcondition.
	if branch, err := GetCurrentBranch(); err != nil || branch != "feature/x" {
		t.Errorf("expected feature/x, got %q, %v", branch, err)
	}
	gitrelChdirOutsideRepo(t)
	if _, err := GetCurrentBranch(); err == nil || err.Error() != "git branch failed: exit status 128" {
		t.Errorf("expected a git branch failure outside a repository, got %v", err)
	}
}

func TestRunCommandVerboseOnError(t *testing.T) {
	t.Run("failure carries the output", func(t *testing.T) {
		newTestRepo(t)

		err := RunCommandVerboseOnError("rev-parse", "--verify", "no-such-ref")

		if err == nil || err.Error() != "exit status 128\nfatal: Needed a single revision\n" {
			t.Errorf("expected the exit status and git output, got %q", err)
		}
	})

	t.Run("silent failure is the bare exit error", func(t *testing.T) {
		repo := newTestRepo(t)
		if err := os.WriteFile(filepath.Join(repo.Dir, "README.md"), []byte("changed"), 0o644); err != nil {
			t.Fatal(err)
		}

		err := RunCommandVerboseOnError("diff", "--quiet")

		if err == nil || err.Error() != "exit status 1" {
			t.Errorf("expected exit status 1, got %v", err)
		}
	})

	t.Run("debug level prints the output on success", func(t *testing.T) {
		repo := newTestRepo(t)
		stop := gitrelDebugToStdout(t)

		err := RunCommandVerboseOnError("rev-parse", "HEAD")
		out := stop()

		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if out != repo.HEAD()+"\n" {
			t.Errorf("expected the HEAD SHA on stdout, got %q", out)
		}
	})
}

func TestRunCommand_debugLevelStreamsStdout(t *testing.T) {
	// Precondition.
	repo := newTestRepo(t)
	stop := gitrelDebugToStdout(t)

	// Under test.
	err := RunCommand("rev-parse", "HEAD")
	out := stop()

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if out != repo.HEAD()+"\n" {
		t.Errorf("expected the HEAD SHA on stdout, got %q", out)
	}
}

func TestPushTag(t *testing.T) {
	// Precondition: a pre-push hook that always fails, and v1 on origin at
	// the first commit.
	origin, work := gittest.InitOriginAndWork(t)
	first := gittest.Commit(t, work, "a.txt")
	gittest.PublishMain(t, work)
	gitrelHooks(t, work, map[string]string{"pre-push": "#!/bin/sh\nexit 1\n"})
	gittest.Git(t, work, "tag", "v1")
	t.Chdir(work)
	if err := PushTag("v1", false, false); err != nil {
		t.Fatalf("expected the push to skip the hook, got %v", err)
	}
	second := gittest.Commit(t, work, "b.txt")
	gittest.Git(t, work, "tag", "-f", "v1", second)

	// Under test and postcondition: --verify runs the hook.
	if err := PushTag("v1", true, true); err == nil {
		t.Error("expected the pre-push hook to fail a verified push")
	}
	if got := gittest.Git(t, origin, "rev-parse", "refs/tags/v1"); got != first {
		t.Errorf("expected origin v1 to stay at %s, got %s", first, got)
	}
	// A moved tag needs force.
	if err := PushTag("v1", false, false); err == nil {
		t.Error("expected origin to reject moving v1 without force")
	}
	if err := PushTag("v1", true, false); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := gittest.Git(t, origin, "rev-parse", "refs/tags/v1"); got != second {
		t.Errorf("expected origin v1 at %s, got %s", second, got)
	}
}

func TestPushNewBranch_verifyRunsPrePushHook(t *testing.T) {
	// Precondition.
	origin, work := gittest.InitOriginAndWork(t)
	sha := gittest.Commit(t, work, "a.txt")
	gittest.PublishMain(t, work)
	gitrelHooks(t, work, map[string]string{"pre-push": "#!/bin/sh\nexit 1\n"})
	t.Chdir(work)

	// Under test.
	err := PushNewBranch(sha, "release/v4.6", true)

	// Postcondition.
	if err == nil {
		t.Fatal("expected the pre-push hook to fail the push")
	}
	if out := gittest.Git(t, origin, "for-each-ref", "refs/heads/release"); out != "" {
		t.Errorf("expected no release branch on origin, got %q", out)
	}
}

func TestBranchExists(t *testing.T) {
	// Precondition.
	repo := newTestRepo(t)
	repo.Git("branch", "release/v1.0")

	// Under test and postcondition.
	if !BranchExists("release/v1.0") {
		t.Error("expected release/v1.0 to exist")
	}
	if BranchExists("release/v2.0") {
		t.Error("expected release/v2.0 to be missing")
	}
	// A tag is not a branch.
	repo.Git("tag", "v3")
	if BranchExists("v3") {
		t.Error("expected tag v3 not to count as a branch")
	}
}

func TestStashChanges_roundTrip(t *testing.T) {
	// Precondition: a modified tracked file and an untracked file.
	repo := newTestRepo(t)
	if err := os.WriteFile(filepath.Join(repo.Dir, "README.md"), []byte("edited"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(repo.Dir, "new.txt"), []byte("new"), 0o644); err != nil {
		t.Fatal(err)
	}

	// Under test.
	result, err := StashChanges()

	// Postcondition.
	if err != nil || !result.Stashed {
		t.Fatalf("expected the changes stashed, got %+v, %v", result, err)
	}
	if out := repo.Git("status", "--porcelain"); out != "" {
		t.Fatalf("expected a clean tree after the stash, got %q", out)
	}
	RestoreStash(result)
	if data, _ := os.ReadFile(filepath.Join(repo.Dir, "README.md")); string(data) != "edited" {
		t.Errorf("expected README.md restored, got %q", data)
	}
	if _, err := os.Stat(filepath.Join(repo.Dir, "new.txt")); err != nil {
		t.Errorf("expected new.txt restored: %v", err)
	}
	if out := repo.Git("stash", "list"); out != "" {
		t.Errorf("expected an empty stash list, got %q", out)
	}
}

func TestStashChanges_cleanTreeStashesNothing(t *testing.T) {
	// Precondition.
	repo := newTestRepo(t)

	// Under test.
	result, err := StashChanges()

	// Postcondition.
	if err != nil || result.Stashed {
		t.Fatalf("expected nothing stashed, got %+v, %v", result, err)
	}
	head := repo.HEAD()
	RestoreStash(result)
	RestoreStash(nil)
	if repo.HEAD() != head || repo.Git("stash", "list") != "" {
		t.Error("expected RestoreStash to do nothing")
	}
}

func TestRestoreStash_conflictKeepsTheStash(t *testing.T) {
	// Precondition: a stashed edit, then a committed edit to the same line.
	repo := newTestRepo(t)
	if err := os.WriteFile(filepath.Join(repo.Dir, "README.md"), []byte("stashed"), 0o644); err != nil {
		t.Fatal(err)
	}
	result, err := StashChanges()
	if err != nil {
		t.Fatal(err)
	}
	repo.Commit("conflicting", "README.md", "committed")
	warnings := gitrelCaptureWarnings(t)

	// Under test.
	RestoreStash(result)

	// Postcondition.
	if out := repo.Git("stash", "list"); !strings.Contains(out, "stash@{0}") {
		t.Errorf("expected the stash kept after a conflict, got %q", out)
	}
	select {
	case msg := <-warnings:
		if !strings.HasPrefix(msg, "Failed to restore stashed changes (may have conflicts): ") {
			t.Errorf("unexpected warning %q", msg)
		}
	default:
		t.Error("expected a warning about the failed restore")
	}
}

func TestGetCommitMessage_unknownCommit(t *testing.T) {
	newTestRepo(t)

	if msg, err := GetCommitMessage("0123456789abcdef0123456789abcdef01234567"); err == nil {
		t.Errorf("expected an error, got message %q", msg)
	}
}

func TestIsCommitAppliedOnBranch_unresolvableInputs(t *testing.T) {
	// Precondition.
	repo := newTestRepo(t)
	sha := repo.Commit("feat: x", "x.txt", "x")

	// Under test and postcondition.
	if IsCommitAppliedOnBranch("0123456789abcdef0123456789abcdef01234567", "main") {
		t.Error("expected an unknown commit not to count as applied")
	}
	if IsCommitAppliedOnBranch(sha, "no-such-branch") {
		t.Error("expected an unknown branch not to hold the commit")
	}
}

func TestFetchCommitWithDepth_withoutOrigin(t *testing.T) {
	newTestRepo(t)

	_, err := FetchCommitWithDepth("origin/main", 1)

	if err == nil || !strings.HasPrefix(err.Error(), "git fetch --depth=1 origin main failed: ") {
		t.Errorf("expected a fetch failure, got %v", err)
	}
}

func TestIsShallowRepository(t *testing.T) {
	t.Run("full clone", func(t *testing.T) {
		newTestRepo(t)
		if shallow, err := IsShallowRepository(); err != nil || shallow {
			t.Errorf("expected false, got %v, %v", shallow, err)
		}
	})
	t.Run("shallow clone", func(t *testing.T) {
		gittest.SetupShallowClone(t)
		if shallow, err := IsShallowRepository(); err != nil || !shallow {
			t.Errorf("expected true, got %v, %v", shallow, err)
		}
	})
	t.Run("outside a repository", func(t *testing.T) {
		gitrelChdirOutsideRepo(t)
		if _, err := IsShallowRepository(); err == nil || !strings.HasPrefix(err.Error(), "git rev-parse --is-shallow-repository failed: ") {
			t.Errorf("expected an error, got %v", err)
		}
	})
}

func TestFetchCommits(t *testing.T) {
	// setup returns a work clone that has not fetched two commits origin holds.
	setup := func(t *testing.T) (a, b string) {
		t.Helper()
		origin, other := gittest.InitOriginAndWork(t)
		gittest.Commit(t, other, "base.txt")
		gittest.PublishMain(t, other)
		work := filepath.Join(t.TempDir(), "work")
		gittest.Git(t, t.TempDir(), "clone", "--quiet", origin, work)
		a = gittest.Commit(t, other, "a.txt")
		b = gittest.Commit(t, other, "b.txt")
		gittest.PublishMain(t, other)
		t.Chdir(work)
		return a, b
	}

	t.Run("no commits is a no-op", func(t *testing.T) {
		gitrelChdirOutsideRepo(t)
		if err := FetchCommits(nil); err != nil {
			t.Errorf("unexpected error: %v", err)
		}
	})

	t.Run("specific commits", func(t *testing.T) {
		a, b := setup(t)
		if err := FetchCommits([]string{a, b}); err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if _, err := ResolveCommit(b); err != nil {
			t.Errorf("expected %s fetched: %v", b, err)
		}
	})

	t.Run("unknown commit falls back to a full fetch", func(t *testing.T) {
		_, b := setup(t)
		if err := FetchCommit("0123456789abcdef0123456789abcdef01234567"); err != nil {
			t.Fatalf("expected the fallback fetch to succeed, got %v", err)
		}
		if _, err := ResolveCommit(b); err != nil {
			t.Errorf("expected the full fetch to bring %s: %v", b, err)
		}
	})

	t.Run("no origin", func(t *testing.T) {
		newTestRepo(t)
		err := FetchCommits([]string{"0123456789abcdef0123456789abcdef01234567"})
		if err == nil || !strings.HasPrefix(err.Error(), "failed to fetch from origin: ") {
			t.Errorf("expected a fetch failure, got %v", err)
		}
	})
}

func TestCherryPickConflictStates(t *testing.T) {
	// Precondition: main and topic change the same line.
	repo := newTestRepo(t)
	gitrelHooks(t, repo.Dir, nil)
	repo.Git("checkout", "--quiet", "-b", "topic")
	topic := repo.Commit("topic change", "README.md", "topic")
	repo.Git("checkout", "--quiet", "main")
	repo.Commit("main change", "README.md", "main")
	repo.Commit("main extra", "extra.txt", "extra")

	if HasMergeConflict() || IsCherryPickInProgress() || HasStagedChanges() || IsRebaseInProgress() {
		t.Fatal("expected no conflict state before the cherry-pick")
	}
	if n, err := CountUniqueCommits("main", "topic"); err != nil || n != 2 {
		t.Errorf("expected 2 commits on main not on topic, got %d, %v", n, err)
	}
	if _, err := CountUniqueCommits("main", "no-such-branch"); err == nil || !strings.HasPrefix(err.Error(), "git rev-list --count failed: ") {
		t.Errorf("expected a rev-list failure, got %v", err)
	}

	// Under test: the cherry-pick stops on the conflict.
	if err := RunCommandVerboseOnError("cherry-pick", topic); err == nil {
		t.Fatal("expected the cherry-pick to conflict")
	}

	// Postcondition.
	if !HasMergeConflict() || !IsCherryPickInProgress() {
		t.Fatal("expected a cherry-pick conflict in progress")
	}
	if err := os.WriteFile(filepath.Join(repo.Dir, "README.md"), []byte("resolved"), 0o644); err != nil {
		t.Fatal(err)
	}
	repo.Git("add", "README.md")
	if HasMergeConflict() || !HasStagedChanges() {
		t.Error("expected the resolution staged with no conflict left")
	}
	if err := RunCherryPickContinue(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if IsCherryPickInProgress() {
		t.Error("expected the cherry-pick finished")
	}
	if msg := repo.Git("log", "-1", "--format=%s"); msg != "topic change" {
		t.Errorf("expected the picked commit's subject, got %q", msg)
	}
}

func TestIsRebaseInProgress_duringAStoppedRebase(t *testing.T) {
	// Precondition.
	repo := newTestRepo(t)
	gitrelHooks(t, repo.Dir, nil)
	repo.Git("checkout", "--quiet", "-b", "topic")
	repo.Commit("topic change", "README.md", "topic")
	repo.Git("checkout", "--quiet", "main")
	repo.Commit("main change", "README.md", "main")
	repo.Git("checkout", "--quiet", "topic")

	// Under test.
	if err := RunCommandVerboseOnError("rebase", "main"); err == nil {
		t.Fatal("expected the rebase to stop on the conflict")
	}

	// Postcondition.
	if !IsRebaseInProgress() {
		t.Error("expected a rebase in progress")
	}
}

func TestCherryPickState_fileErrors(t *testing.T) {
	t.Run("outside a repository", func(t *testing.T) {
		gitrelChdirOutsideRepo(t)
		prefix := "failed to determine state file path: git rev-parse --git-dir failed: "
		if err := SaveCherryPickState(&CherryPickState{}); err == nil || !strings.HasPrefix(err.Error(), prefix) {
			t.Errorf("expected a path error from save, got %v", err)
		}
		if _, err := LoadCherryPickState(); err == nil || !strings.HasPrefix(err.Error(), prefix) {
			t.Errorf("expected a path error from load, got %v", err)
		}
		CleanCherryPickState()
	})

	t.Run("corrupt file", func(t *testing.T) {
		repo := newTestRepo(t)
		if err := os.WriteFile(filepath.Join(repo.Dir, ".git", cherryPickStateFile), []byte("{"), 0o644); err != nil {
			t.Fatal(err)
		}
		if _, err := LoadCherryPickState(); err == nil || !strings.HasPrefix(err.Error(), "failed to parse state file: ") {
			t.Errorf("expected a parse error, got %v", err)
		}
		CleanCherryPickState()
		if _, err := os.Stat(filepath.Join(repo.Dir, ".git", cherryPickStateFile)); !os.IsNotExist(err) {
			t.Errorf("expected the state file removed, got %v", err)
		}
	})

	t.Run("path is a directory", func(t *testing.T) {
		repo := newTestRepo(t)
		path := filepath.Join(repo.Dir, ".git", cherryPickStateFile)
		if err := os.MkdirAll(filepath.Join(path, "child"), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := SaveCherryPickState(&CherryPickState{}); err == nil || !strings.HasPrefix(err.Error(), "failed to write state file: ") {
			t.Errorf("expected a write error, got %v", err)
		}
		if _, err := LoadCherryPickState(); err == nil || !strings.HasPrefix(err.Error(), "failed to read state file: ") {
			t.Errorf("expected a read error, got %v", err)
		}
		warnings := gitrelCaptureWarnings(t)
		CleanCherryPickState()
		select {
		case msg := <-warnings:
			if !strings.HasPrefix(msg, "Failed to remove state file ") {
				t.Errorf("unexpected warning %q", msg)
			}
		default:
			t.Error("expected a warning about the state file")
		}
	})
}
