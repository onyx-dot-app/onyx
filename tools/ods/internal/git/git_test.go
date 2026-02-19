package git

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// testRepo wraps a temporary git repo with convenience methods for tests.
type testRepo struct {
	t      *testing.T
	Dir    string
	origWd string
}

func newTestRepo(t *testing.T) *testRepo {
	t.Helper()
	dir := t.TempDir()
	origWd, _ := os.Getwd()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}

	r := &testRepo{t: t, Dir: dir, origWd: origWd}
	t.Cleanup(r.cleanup)

	r.Git("init", "-b", "main")
	r.Git("config", "user.email", "test@test.com")
	r.Git("config", "user.name", "Test")
	r.Commit("initial commit", "README.md", "init")

	return r
}

func (r *testRepo) cleanup() {
	_ = os.Chdir(r.origWd)
}

// Git runs a git command, failing the test on error.
func (r *testRepo) Git(args ...string) string {
	r.t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = r.Dir
	out, err := cmd.CombinedOutput()
	if err != nil {
		r.t.Fatalf("git %s failed: %v\n%s", strings.Join(args, " "), err, out)
	}
	return strings.TrimSpace(string(out))
}

// Commit creates a file, stages it, and commits with the given message.
func (r *testRepo) Commit(msg, filename, content string) string {
	r.t.Helper()
	path := filepath.Join(r.Dir, filename)
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		r.t.Fatal(err)
	}
	r.Git("add", filename)
	r.Git("commit", "-m", msg)
	return r.HEAD()
}

// HEAD returns the SHA of the current HEAD.
func (r *testRepo) HEAD() string {
	r.t.Helper()
	return r.Git("rev-parse", "HEAD")
}

// --- State file tests ---

func TestCherryPickStateRoundTrip(t *testing.T) {
	newTestRepo(t)

	state := &CherryPickState{
		OriginalBranch: "main",
		CommitSHAs:     []string{"abc123", "def456"},
		CommitMessages: []string{"fix: something", "feat: another"},
		Releases:       []string{"v2.12"},
		Stashed:        true,
		NoVerify:       false,
		DryRun:         true,
		BranchSuffix:   "abc123-def456",
		PRTitle:        "chore(hotfix): cherry-pick 2 commits",
	}

	if err := SaveCherryPickState(state); err != nil {
		t.Fatalf("SaveCherryPickState: %v", err)
	}

	loaded, err := LoadCherryPickState()
	if err != nil {
		t.Fatalf("LoadCherryPickState: %v", err)
	}

	if loaded.OriginalBranch != state.OriginalBranch {
		t.Errorf("OriginalBranch = %q, want %q", loaded.OriginalBranch, state.OriginalBranch)
	}
	if len(loaded.CommitSHAs) != len(state.CommitSHAs) {
		t.Errorf("CommitSHAs len = %d, want %d", len(loaded.CommitSHAs), len(state.CommitSHAs))
	}
	if loaded.Stashed != state.Stashed {
		t.Errorf("Stashed = %v, want %v", loaded.Stashed, state.Stashed)
	}
	if loaded.DryRun != state.DryRun {
		t.Errorf("DryRun = %v, want %v", loaded.DryRun, state.DryRun)
	}

	CleanCherryPickState()

	if _, err = LoadCherryPickState(); err == nil {
		t.Error("LoadCherryPickState after clean should fail")
	}
}

func TestLoadCherryPickStateMissing(t *testing.T) {
	newTestRepo(t)

	if _, err := LoadCherryPickState(); err == nil {
		t.Error("expected error for missing state file")
	}
}

// --- IsCommitAppliedOnBranch tests ---

func TestIsCommitAppliedOnBranch_ExactSHA(t *testing.T) {
	repo := newTestRepo(t)
	sha := repo.HEAD()

	if !IsCommitAppliedOnBranch(sha, "main") {
		t.Error("expected commit to be found on main by exact SHA")
	}
}

func TestIsCommitAppliedOnBranch_SubjectMatch(t *testing.T) {
	repo := newTestRepo(t)

	repo.Git("checkout", "-b", "feature")
	featureSHA := repo.Commit("feat: add feature", "feature.txt", "feature")

	// Diverge main so the feature SHA isn't reachable from it
	repo.Git("checkout", "main")
	repo.Commit("chore: diverge main", "diverge.txt", "diverge")
	repo.Git("cherry-pick", featureSHA)

	if CommitExistsOnBranch(featureSHA, "main") {
		t.Skip("exact SHA reachable from main, cannot test subject-line fallback")
	}

	if !IsCommitAppliedOnBranch(featureSHA, "main") {
		t.Error("expected IsCommitAppliedOnBranch to find cherry-picked commit by subject")
	}
}

func TestIsCommitAppliedOnBranch_NoMatch(t *testing.T) {
	repo := newTestRepo(t)

	repo.Git("checkout", "-b", "feature")
	featureSHA := repo.Commit("feat: only on feature branch", "only-feature.txt", "only")

	if IsCommitAppliedOnBranch(featureSHA, "main") {
		t.Error("expected commit NOT to be found on main")
	}
}

func TestIsCommitAppliedOnBranch_NoFalsePositiveFromBody(t *testing.T) {
	repo := newTestRepo(t)

	repo.Git("checkout", "-b", "feature")
	featureSHA := repo.Commit("unique subject for test", "f.txt", "f")

	// On main, create a commit whose body contains the subject but whose subject differs
	repo.Git("checkout", "main")
	repo.Commit("different subject\n\nunique subject for test", "g.txt", "g")

	if IsCommitAppliedOnBranch(featureSHA, "main") {
		t.Error("should NOT match when subject only appears in body of another commit")
	}
}
