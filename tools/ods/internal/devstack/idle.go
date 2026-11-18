package devstack

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

// agentCommands are the coding agent CLIs whose working directory marks a
// worktree as in use.
var agentCommands = []string{"claude", "codex", "opencode", "cursor-agent"}

// AgentDirs returns the working directory of each running coding agent. It
// reads /proc on Linux and lsof on macOS. It fails on other systems and when
// the lookup cannot run, because an empty list would make every stack look
// idle.
func AgentDirs() ([]string, error) {
	var dirs []string
	switch runtime.GOOS {
	case "linux":
		procs, err := filepath.Glob("/proc/[0-9]*")
		if err != nil || len(procs) == 0 {
			return nil, fmt.Errorf("cannot read /proc to find coding agents: %v", err)
		}
		for _, proc := range procs {
			comm, err := os.ReadFile(filepath.Join(proc, "comm"))
			if err != nil || !isAgentCommand(strings.TrimSpace(string(comm))) {
				continue
			}
			if dir, err := os.Readlink(filepath.Join(proc, "cwd")); err == nil {
				dirs = append(dirs, dir)
			}
		}
	case "darwin":
		args := []string{"-a", "-d", "cwd", "-Fn"}
		for _, name := range agentCommands {
			args = append(args, "-c", name)
		}
		out, err := exec.Command("lsof", args...).Output()
		// lsof exits 1 with no output when no process matches.
		var exitErr *exec.ExitError
		noMatch := errors.As(err, &exitErr) && exitErr.ExitCode() == 1 && len(out) == 0
		if err != nil && !noMatch {
			return nil, fmt.Errorf("cannot run lsof to find coding agents: %w", err)
		}
		for _, line := range strings.Split(string(out), "\n") {
			if dir, ok := strings.CutPrefix(line, "n"); ok && dir != "" {
				dirs = append(dirs, dir)
			}
		}
	default:
		return nil, fmt.Errorf("finding coding agents is not supported on %s", runtime.GOOS)
	}
	return dirs, nil
}

func isAgentCommand(name string) bool {
	for _, agent := range agentCommands {
		if name == agent {
			return true
		}
	}
	return false
}

// LastActivity is the latest sign of work on a stack: its start or last
// `stack up`, `restart` or `stop` (which rewrite the state), a Git
// operation in its checkout (commit, checkout, add, rebase), or a change to a
// modified, deleted or untracked file. A coding agent that runs in the checkout counts
// as activity at now. Ignored files such as logs do not count, because a
// running stack writes them while nobody works.
func LastActivity(row StackRow, agentDirs []string, now time.Time) time.Time {
	latest := row.Since
	if row.state != nil && row.state.UpdatedAt.After(latest) {
		latest = row.state.UpdatedAt
	}
	if row.Root == "" || !row.RootExists {
		return latest
	}
	roots := []string{row.Root}
	if resolved, err := filepath.EvalSymlinks(row.Root); err == nil && resolved != row.Root {
		roots = append(roots, resolved)
	}
	for _, dir := range agentDirs {
		for _, root := range roots {
			if dir == root || strings.HasPrefix(dir, root+string(filepath.Separator)) {
				return now
			}
		}
	}
	later := func(t time.Time) {
		if t.After(latest) {
			latest = t
		}
	}
	if gitDir, err := gitOutput(row.Root, "rev-parse", "--absolute-git-dir"); err == nil {
		for _, name := range []string{"HEAD", "index", filepath.Join("logs", "HEAD")} {
			if info, err := os.Stat(filepath.Join(gitDir, name)); err == nil {
				later(info.ModTime())
			}
		}
	}
	cmd := exec.Command("git", "ls-files", "-z", "--modified", "--others", "--exclude-standard")
	cmd.Dir = row.Root
	if out, err := cmd.Output(); err == nil {
		for _, name := range strings.Split(string(out), "\x00") {
			if name == "" {
				continue
			}
			path := filepath.Join(row.Root, name)
			info, err := os.Lstat(path)
			if errors.Is(err, os.ErrNotExist) {
				// A deleted tracked file changes the mtime of its directory.
				info, err = os.Stat(filepath.Dir(path))
			}
			if err == nil {
				later(info.ModTime())
			}
		}
	}
	return latest
}

// Idle reports whether row is a running isolated stack in an existing
// worktree with no activity since cutoff. Shared stacks serve several
// worktrees, so they are never idle by this rule.
func Idle(row StackRow, cutoff time.Time, activity func(StackRow) time.Time) bool {
	if row.Mode != Isolated || row.state == nil || !row.Running() || !row.RootExists || !row.Worktree {
		return false
	}
	switch row.Status {
	case StatusActive, StatusAppStopped, StatusInfraOnly:
	default:
		return false
	}
	return activity(row).Before(cutoff)
}
