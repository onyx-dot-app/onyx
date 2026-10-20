//go:build integration

package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// TestStackLiveOrphanedWorktree starts an isolated stack in a disposable
// worktree of ODS_STACK_LIVE_ROOT_A, deletes the worktree, and checks that
// `stack ls --orphaned` finds the stack and `stack down --project` stops it.
func TestStackLiveOrphanedWorktree(t *testing.T) {
	base := configuredStack(t, "ODS_STACK_LIVE_ROOT_A")
	worktree := filepath.Join(t.TempDir(), "orphan-worktree")
	if out, err := exec.Command("git", "-C", base.root, "worktree", "add", "--detach", worktree).CombinedOutput(); err != nil {
		t.Fatalf("git worktree add: %v\n%s", err, out)
	}
	worktree, err := filepath.EvalSymlinks(worktree)
	if err != nil {
		t.Fatal(err)
	}
	stack := liveStack{root: worktree, binary: base.binary, client: base.client}
	project := ""
	t.Cleanup(func() {
		if project != "" {
			_, _, _ = runODS(t, base.binary, t.TempDir(), "stack", "down", "--project", project, "--force")
		}
		_ = os.RemoveAll(worktree)
		_ = exec.Command("git", "-C", base.root, "worktree", "prune").Run()
	})

	status := stack.up(t)
	project = status.Project
	var pids []int
	for _, service := range status.Services {
		if service.PID > 0 {
			pids = append(pids, service.PID)
		}
	}
	if len(pids) == 0 {
		t.Fatalf("stack has no running services: %+v", status)
	}

	// Delete the checkout without git, so its state in the common Git
	// directory survives and records the live processes.
	if err := os.RemoveAll(worktree); err != nil {
		t.Fatal(err)
	}

	outside := t.TempDir()
	out, code, err := runODS(t, base.binary, outside, "stack", "ls", "--orphaned", "--json")
	if code != 3 {
		t.Fatalf("ls --orphaned exit %d, want 3: %v\n%s", code, err, out)
	}
	var rows []devstack.StackRow
	if err := json.Unmarshal(out, &rows); err != nil {
		t.Fatalf("invalid ls JSON: %v\n%s", err, out)
	}
	found := false
	for _, row := range rows {
		if row.Project == project && row.Status == devstack.StatusOrphaned && !row.RootExists {
			found = true
		}
	}
	if !found {
		t.Fatalf("ls --orphaned does not list %s: %s", project, out)
	}

	if out, code, err := runODS(t, base.binary, outside, "stack", "down", "--project", project); code != 0 {
		t.Fatalf("down --project exit %d: %v\n%s", code, err, out)
	}
	for _, pid := range pids {
		if err := syscall.Kill(pid, 0); err == nil {
			t.Errorf("service pid %d still runs after down --project", pid)
		}
	}
	if containers := dockerOutput(t, "ps", "-a", "--filter", "label=com.docker.compose.project="+project, "--format", "{{.Names}}"); containers != "" {
		t.Fatalf("down --project left containers: %s", containers)
	}
	leases, err := (&devstack.Registry{Dir: filepath.Join(paths.DataDir(), "stack")}).Leases()
	if err != nil {
		t.Fatal(err)
	}
	for _, lease := range leases {
		if lease.Root == worktree {
			t.Errorf("down --project kept lease %s=%d", lease.Name, lease.Port)
		}
	}
	if out, code, err := runODS(t, base.binary, outside, "stack", "ls", "--orphaned", "--json"); code != 0 {
		t.Fatalf("ls --orphaned after down exit %d: %v\n%s", code, err, out)
	}
	project = ""
}

// runODS runs ODS in dir and returns stdout and the exit code.
func runODS(t *testing.T, binary, dir string, args ...string) ([]byte, int, error) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, binary, args...)
	cmd.Dir = dir
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	err := cmd.Run()
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return stdout.Bytes(), exitErr.ExitCode(), fmt.Errorf("%w\n%s", err, stderr.String())
	}
	if err != nil {
		return stdout.Bytes(), -1, err
	}
	return stdout.Bytes(), 0, nil
}
