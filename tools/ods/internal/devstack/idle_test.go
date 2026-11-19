package devstack

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func gitRepo(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	for _, args := range [][]string{
		{"init", "-q"},
		{"-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "init"},
	} {
		cmd := exec.Command("git", args...)
		cmd.Dir = root
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	writeFile(t, filepath.Join(root, ".gitignore"), "log/\n")
	return root
}

// age sets the modification time of every file in the repository, including
// .git, to when.
func age(t *testing.T, root string, when time.Time) {
	t.Helper()
	err := filepath.Walk(root, func(path string, _ os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		return os.Chtimes(path, when, when)
	})
	if err != nil {
		t.Fatal(err)
	}
}

func writeFile(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func lastActivity(t *testing.T, row StackRow, agents []string, now time.Time) time.Time {
	t.Helper()
	got, err := LastActivity(row, agents, now)
	if err != nil {
		t.Fatal(err)
	}
	return got
}

func TestLastActivityFailsWhenGitCannotReadTheCheckout(t *testing.T) {
	root := gitRepo(t)
	if err := os.WriteFile(filepath.Join(root, ".git", "index"), []byte("corrupt"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LastActivity(StackRow{Root: root, RootExists: true}, nil, time.Now()); err == nil {
		t.Fatal("an unreadable index counted as no activity")
	}
}

func TestLastActivityCountsGitAndUntrackedEditsButNotIgnoredFiles(t *testing.T) {
	root := gitRepo(t)
	old := time.Now().Add(-48 * time.Hour)
	started := time.Now().Add(-24 * time.Hour)
	row := StackRow{Root: root, RootExists: true, Since: started}
	age(t, root, old)
	if got := lastActivity(t, row, nil, time.Now()); !got.Equal(started) {
		t.Fatalf("quiet checkout: activity %s, want the stack start %s", got, started)
	}

	writeFile(t, filepath.Join(root, "log", "api.log"), "line")
	if got := lastActivity(t, row, nil, time.Now()); !got.Equal(started) {
		t.Fatalf("an ignored log write counted as activity: %s", got)
	}

	writeFile(t, filepath.Join(root, "new.go"), "package x")
	if got := lastActivity(t, row, nil, time.Now()); !got.After(started) {
		t.Fatalf("an untracked edit did not count: %s", got)
	}

	age(t, root, old)
	if err := os.Chtimes(filepath.Join(root, ".git", "HEAD"), time.Now(), time.Now()); err != nil {
		t.Fatal(err)
	}
	if got := lastActivity(t, row, nil, time.Now()); !got.After(started) {
		t.Fatalf("a git operation did not count: %s", got)
	}

	tracked := filepath.Join(root, "docs", "tracked.md")
	writeFile(t, tracked, "x")
	for _, args := range [][]string{{"add", "docs"}, {"-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "docs"}} {
		cmd := exec.Command("git", args...)
		cmd.Dir = root
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	age(t, root, old)
	if err := os.Remove(tracked); err != nil {
		t.Fatal(err)
	}
	if got := lastActivity(t, row, nil, time.Now()); !got.After(started) {
		t.Fatalf("a deleted tracked file did not count: %s", got)
	}

	nested := filepath.Join(root, "pkg", "sub", "gone.go")
	writeFile(t, nested, "x")
	for _, args := range [][]string{{"add", "pkg"}, {"-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "pkg"}} {
		cmd := exec.Command("git", args...)
		cmd.Dir = root
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	age(t, root, old)
	if err := os.RemoveAll(filepath.Join(root, "pkg")); err != nil {
		t.Fatal(err)
	}
	if got := lastActivity(t, row, nil, time.Now()); !got.After(started) {
		t.Fatalf("a deleted tracked directory did not count: %s", got)
	}

	if got := lastActivity(t, StackRow{Root: "/nonexistent", Since: started}, nil, time.Now()); !got.Equal(started) {
		t.Fatalf("missing checkout: activity %s, want %s", got, started)
	}
}

func TestIdleOnlyMatchesRunningIsolatedStacksInAWorktree(t *testing.T) {
	now := time.Now()
	cutoff := now.Add(-6 * time.Hour)
	quiet := func(StackRow) time.Time { return now.Add(-7 * time.Hour) }
	busy := func(StackRow) time.Time { return now.Add(-time.Hour) }
	base := StackRow{Mode: Isolated, state: &State{}, RootExists: true, Worktree: true, Status: StatusInfraOnly,
		Infra: &InfraCount{Running: 7, Total: 7}}

	if !Idle(base, cutoff, quiet) {
		t.Error("a quiet isolated stack is not idle")
	}
	if Idle(base, cutoff, busy) {
		t.Error("a stack with recent activity is idle")
	}
	for name, change := range map[string]func(*StackRow){
		"shared":       func(r *StackRow) { r.Mode = Shared },
		"frontend":     func(r *StackRow) { r.Mode = Frontend },
		"compose-only": func(r *StackRow) { r.state = nil },
		"stopped":      func(r *StackRow) { r.Infra = &InfraCount{Total: 7}; r.Status = StatusStopped },
		"orphaned":     func(r *StackRow) { r.Status = StatusOrphaned },
		"not-worktree": func(r *StackRow) { r.Worktree = false },
	} {
		row := base
		change(&row)
		if Idle(row, cutoff, quiet) {
			t.Errorf("%s stack counted as idle", name)
		}
	}
}

func TestRestartingAStackWithRunningContainersCountsAsActivity(t *testing.T) {
	root := gitRepo(t)
	age(t, root, time.Now().Add(-48*time.Hour))
	m := &fakeMachine{alivePIDs: map[int]bool{61: true}}
	m.worktree(root, "feature")
	m.containers = onyxContainers("restarted-1", root, true, time.Now().Add(-7*time.Hour))
	state := isolatedState("/repo/.git", "restarted", "restarted-1", root, PhaseReady, 61)
	state.State.UpdatedAt = time.Now().Add(-10 * time.Minute)
	m.states = []stateRecord{state}
	row := rowFor(t, buildInventory(m.input()), "restarted-1")
	activity := func(r StackRow) time.Time { return lastActivity(t, r, nil, time.Now()) }
	if Idle(row, time.Now().Add(-6*time.Hour), activity) {
		t.Fatalf("a stack restarted 10 minutes ago counted as idle: since %s", row.Since)
	}
}

func TestLastActivityIsNowWhileAnAgentRunsInTheCheckout(t *testing.T) {
	root := gitRepo(t)
	age(t, root, time.Now().Add(-48*time.Hour))
	row := StackRow{Root: root, RootExists: true, Since: time.Now().Add(-24 * time.Hour)}
	now := time.Now()
	if got := lastActivity(t, row, []string{filepath.Join(root, "backend")}, now); !got.Equal(now) {
		t.Fatalf("an agent in a subdirectory did not count: %s", got)
	}
	if got := lastActivity(t, row, []string{root + "-other"}, now); got.Equal(now) {
		t.Fatal("an agent in a sibling directory with the same prefix counted")
	}
	link := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(root, link); err != nil {
		t.Fatal(err)
	}
	resolved, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	linked := StackRow{Root: link, RootExists: true, Since: row.Since}
	if got := lastActivity(t, linked, []string{resolved}, now); !got.Equal(now) {
		t.Fatalf("an agent in the resolved path of a symlinked checkout did not count: %s", got)
	}
}
