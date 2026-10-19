package devstack

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

// ComposeDownFunc runs `docker compose -p project down` for a project.
type ComposeDownFunc func(ctx context.Context, project string, volumes bool) error

// ProjectOptions tune StopProject, DownProject and CleanupRow.
type ProjectOptions struct {
	StopTimeout time.Duration
	LockWait    time.Duration
	// Force stops a stack that still runs in an existing worktree.
	Force bool
	// Volumes also removes the Compose volumes.
	Volumes  bool
	Discover DiscoverOptions
}

// ProjectResult reports what a project stop or down changed.
type ProjectResult struct {
	Row             StackRow
	StoppedServices int
	ComposeDown     bool
	ReleasedLeases  int
	RemovedOwner    bool
}

// StopProject stops the application processes recorded for project,
// wherever its checkout is. The infrastructure keeps running.
func StopProject(ctx context.Context, registry *Registry, project string, opts ProjectOptions) (*ProjectResult, error) {
	row, err := FindProject(registry, project, opts.Discover)
	if err != nil {
		return nil, err
	}
	return CleanupRow(ctx, registry, row, nil, opts)
}

// DownProject stops the application processes and the Compose
// infrastructure of project, wherever its checkout is, then releases the
// stack's port leases. Volumes are kept unless opts.Volumes is set.
func DownProject(ctx context.Context, registry *Registry, project string, compose ComposeDownFunc, opts ProjectOptions) (*ProjectResult, error) {
	if compose == nil {
		return nil, errors.New("no Compose runner")
	}
	row, err := FindProject(registry, project, opts.Discover)
	if err != nil {
		return nil, err
	}
	return CleanupRow(ctx, registry, row, compose, opts)
}

// FindProject resolves the stack that owns a Compose project: the state
// named by its owner record, else any state that claims it, else its
// Docker containers.
func FindProject(registry *Registry, project string, opts DiscoverOptions) (StackRow, error) {
	project = docker.NormalizeProjectName(project)
	inv := Discover(registry, opts)
	ownerDir := ""
	if registry != nil {
		if owner := readOwner(ownerPath(registry, project)); owner.Err == nil {
			ownerDir = owner.StateDir
		}
	}
	var fallback *StackRow
	for i := range inv.Rows {
		row := &inv.Rows[i]
		if row.Project != project || row.Mode == Frontend || row.Status == StatusStaleLease {
			continue
		}
		if ownerDir != "" && row.StateDir == ownerDir {
			return *row, nil
		}
		if fallback == nil || (fallback.Infra == nil && row.Infra != nil) {
			fallback = row
		}
	}
	if fallback != nil {
		return *fallback, nil
	}
	return StackRow{}, fmt.Errorf("no dev stack found for project %s; list stacks with 'ods stack ls --all'", project)
}

func ownerPath(registry *Registry, project string) string {
	return filepath.Join(registry.Dir, projectsDirName, ProjectName(project), ownerFileName)
}

// CleanupRow stops the live processes recorded for row and, with compose,
// runs Compose down for its project, releases its port leases, and removes
// the owner record of an orphan. It refuses a stack that still runs in an
// existing worktree unless opts.Force is set.
func CleanupRow(ctx context.Context, registry *Registry, row StackRow, compose ComposeDownFunc, opts ProjectOptions) (*ProjectResult, error) {
	result := &ProjectResult{Row: row}
	var stack *Stack
	if row.StateDir != "" && pathExists(row.StateDir) {
		stack = &Stack{StateDir: row.StateDir, Project: row.Project, Mode: row.Mode, Root: row.Root}
		release, err := stack.Lock(ctx, "stack down --project", opts.LockWait)
		if err != nil {
			return nil, err
		}
		defer release()
	}
	infra := compose != nil && row.Mode != Frontend && row.Project != ""
	if infra && registry != nil {
		lock := &Stack{StateDir: filepath.Join(registry.Dir, projectsDirName, ProjectName(row.Project))}
		release, err := lock.Lock(ctx, "stack down --project", opts.LockWait)
		if err != nil {
			return nil, err
		}
		defer release()
	}

	if stack != nil {
		st, err := stack.ReadState()
		if err != nil {
			return nil, err
		}
		if st != nil && st.Project == row.Project {
			if !opts.Force && liveInWorktree(st) {
				flag := ""
				if row.Mode == Isolated {
					flag = "--isolated "
				}
				return nil, fmt.Errorf("project %s still runs in the worktree %s; run 'cd %s && ods %sstack down', or add --force to stop it from here", row.Project, st.Root, shellQuote(st.Root), flag)
			}
			for _, rec := range st.Services {
				if rec.Skipped == "" && groupIsOurs(rec) {
					result.StoppedServices++
				}
			}
			if err := stack.stopServices(opts.StopTimeout); err != nil {
				return result, err
			}
		}
	}
	if compose == nil {
		return result, nil
	}
	if infra && !ownedElsewhere(registry, row) {
		if err := compose(ctx, row.Project, opts.Volumes); err != nil {
			return result, err
		}
		result.ComposeDown = true
	}
	if registry == nil {
		return result, nil
	}
	if row.LeaseRoot != "" {
		if err := registry.Release(row.LeaseRoot); err != nil {
			return result, err
		}
		result.ReleasedLeases = len(row.Leases)
	}
	if row.Status == StatusOrphaned && row.Project != "" {
		removed, err := removeOrphanOwner(registry, row)
		if err != nil {
			return result, err
		}
		result.RemovedOwner = removed
	}
	return result, nil
}

// liveInWorktree reports whether st has a live service under a checkout
// that still exists as a git worktree.
func liveInWorktree(st *State) bool {
	if st.Root == "" || !pathExists(st.Root) || !inspectCheckout(st.Root).Worktree {
		return false
	}
	for _, rec := range st.Services {
		if rec.Skipped == "" && groupIsOurs(rec) {
			return true
		}
	}
	return false
}

func removeOrphanOwner(registry *Registry, row StackRow) (bool, error) {
	path := ownerPath(registry, row.Project)
	owner := readOwner(path)
	if errors.Is(owner.Err, os.ErrNotExist) {
		return false, nil
	}
	if owner.Err == nil && owner.StateDir != row.StateDir && pathExists(filepath.Join(owner.StateDir, stateFileName)) {
		return false, nil
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return false, err
	}
	return true, nil
}

// ownedElsewhere reports whether the project's owner record names another
// state that still exists, so row must not stop the project's containers.
func ownedElsewhere(registry *Registry, row StackRow) bool {
	if registry == nil {
		return false
	}
	owner := readOwner(ownerPath(registry, row.Project))
	return owner.Err == nil && owner.StateDir != row.StateDir && pathExists(filepath.Join(owner.StateDir, stateFileName))
}
