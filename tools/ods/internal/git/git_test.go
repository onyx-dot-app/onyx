package git

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestCherryPickStateRoundTrip(t *testing.T) {
	_, cleanup := initTestRepo(t)
	defer cleanup()

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

	_, err = LoadCherryPickState()
	if err == nil {
		t.Error("LoadCherryPickState after clean should fail")
	}
}

func TestLoadCherryPickStateMissing(t *testing.T) {
	_, cleanup := initTestRepo(t)
	defer cleanup()

	_, err := LoadCherryPickState()
	if err == nil {
		t.Error("expected error for missing state file")
	}
}

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}
}

// initTestRepo creates a real git repo in a temp dir with an initial commit,
// changes into it, and returns a cleanup function.
func initTestRepo(t *testing.T) (repoDir string, cleanup func()) {
	t.Helper()
	dir := t.TempDir()

	origDir, _ := os.Getwd()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}

	run := func(args ...string) {
		t.Helper()
		cmd := exec.Command("git", args...)
		cmd.Dir = dir
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v failed: %v\n%s", args, err, out)
		}
	}

	run("init", "-b", "main")
	run("config", "user.email", "test@test.com")
	run("config", "user.name", "Test")

	f := filepath.Join(dir, "README.md")
	writeFile(t, f, "init")
	run("add", "README.md")
	run("commit", "-m", "initial commit")

	return dir, func() {
		_ = os.Chdir(origDir)
	}
}

func TestIsCommitAppliedOnBranch_ExactSHA(t *testing.T) {
	dir, cleanup := initTestRepo(t)
	defer cleanup()

	// Get the SHA of HEAD
	cmd := exec.Command("git", "rev-parse", "HEAD")
	cmd.Dir = dir
	out, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	sha := string(out[:len(out)-1])

	if !IsCommitAppliedOnBranch(sha, "main") {
		t.Error("expected commit to be found on main by exact SHA")
	}
}

func TestIsCommitAppliedOnBranch_SubjectMatch(t *testing.T) {
	dir, cleanup := initTestRepo(t)
	defer cleanup()

	run := func(args ...string) {
		t.Helper()
		cmd := exec.Command("git", args...)
		cmd.Dir = dir
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v failed: %v\n%s", args, err, out)
		}
	}

	// Create a feature branch with a commit
	run("checkout", "-b", "feature")
	writeFile(t, filepath.Join(dir, "feature.txt"), "feature")
	run("add", "feature.txt")
	run("commit", "-m", "feat: add feature")

	cmd := exec.Command("git", "rev-parse", "HEAD")
	cmd.Dir = dir
	out, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	featureSHA := string(out[:len(out)-1])

	// Make main diverge so the feature SHA isn't reachable from main
	run("checkout", "main")
	writeFile(t, filepath.Join(dir, "diverge.txt"), "diverge")
	run("add", "diverge.txt")
	run("commit", "-m", "chore: diverge main")

	// Cherry-pick onto main (creates new SHA, same subject)
	run("cherry-pick", featureSHA)

	// The original SHA should NOT be on main (different history)
	if CommitExistsOnBranch(featureSHA, "main") {
		t.Skip("exact SHA is on main (unexpected), skipping subject-line test")
	}

	if !IsCommitAppliedOnBranch(featureSHA, "main") {
		t.Error("expected IsCommitAppliedOnBranch to find cherry-picked commit by subject")
	}
}

func TestIsCommitAppliedOnBranch_NoMatch(t *testing.T) {
	dir, cleanup := initTestRepo(t)
	defer cleanup()

	run := func(args ...string) {
		t.Helper()
		cmd := exec.Command("git", args...)
		cmd.Dir = dir
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v failed: %v\n%s", args, err, out)
		}
	}

	// Create a commit only on a feature branch
	run("checkout", "-b", "feature")
	writeFile(t, filepath.Join(dir, "only-feature.txt"), "only")
	run("add", "only-feature.txt")
	run("commit", "-m", "feat: only on feature branch")

	cmd := exec.Command("git", "rev-parse", "HEAD")
	cmd.Dir = dir
	out, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	featureSHA := string(out[:len(out)-1])

	if IsCommitAppliedOnBranch(featureSHA, "main") {
		t.Error("expected commit NOT to be found on main")
	}
}

func TestIsCommitAppliedOnBranch_NoFalsePositiveFromBody(t *testing.T) {
	dir, cleanup := initTestRepo(t)
	defer cleanup()

	run := func(args ...string) {
		t.Helper()
		cmd := exec.Command("git", args...)
		cmd.Dir = dir
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v failed: %v\n%s", args, err, out)
		}
	}

	// Create a commit on feature with a unique subject
	run("checkout", "-b", "feature")
	writeFile(t, filepath.Join(dir, "f.txt"), "f")
	run("add", "f.txt")
	run("commit", "-m", "unique subject for test")

	cmd := exec.Command("git", "rev-parse", "HEAD")
	cmd.Dir = dir
	out, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	featureSHA := string(out[:len(out)-1])

	// On main, create a commit whose BODY contains the subject, but subject differs
	run("checkout", "main")
	writeFile(t, filepath.Join(dir, "g.txt"), "g")
	run("add", "g.txt")
	run("commit", "-m", "different subject\n\nunique subject for test")

	if IsCommitAppliedOnBranch(featureSHA, "main") {
		t.Error("should NOT match when subject only appears in body of another commit")
	}
}
