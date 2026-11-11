package devstack

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

func (s *Stack) LockInfrastructure(ctx context.Context, wait time.Duration) (func(), error) {
	if s.Registry == nil {
		return nil, fmt.Errorf("no port registry")
	}
	lock := &Stack{StateDir: filepath.Join(s.Registry.Dir, "projects", ProjectName(s.Project))}
	release, err := lock.Lock(ctx, "infrastructure lifecycle", wait)
	if err != nil {
		return nil, err
	}
	if s.Mode == Isolated {
		shared, err := Open(s.Root, "", Shared)
		if err == nil {
			var st *State
			st, err = shared.ReadState()
			if st != nil && st.Project == s.Project {
				err = fmt.Errorf("project %s now belongs to shared infrastructure; choose a different --project for isolated data", s.Project)
			}
		}
		if err != nil {
			release()
			return nil, err
		}
	}
	if err := s.claimProject(lock.StateDir); err != nil {
		release()
		return nil, err
	}
	return release, nil
}

type projectOwner struct {
	StateDir string `json:"state_dir"`
}

func (s *Stack) claimProject(dir string) error {
	path := filepath.Join(dir, "owner.json")
	data, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if err == nil {
		var owner projectOwner
		if err := json.Unmarshal(data, &owner); err != nil {
			return fmt.Errorf("parse project owner: %w", err)
		}
		if owner.StateDir == "" {
			return fmt.Errorf("project %s has an invalid owner record", s.Project)
		}
		if owner.StateDir == s.StateDir {
			return nil
		}
		st, err := (&Stack{StateDir: owner.StateDir}).ReadState()
		if err != nil {
			return err
		}
		if st != nil && st.Project == s.Project && (st.Phase != PhaseStopped || len(st.Services) > 0) {
			return fmt.Errorf("project %s is owned by %s; stop that stack or select another --project", s.Project, st.Root)
		}
	} else {
		shared, err := Open(s.Root, "", Shared)
		if err != nil {
			return err
		}
		legacy, err := shared.legacyStates()
		if err != nil {
			return err
		}
		for _, candidate := range legacy {
			st := candidate.State
			if candidate.Dir != s.StateDir && st.Project == s.Project && (st.Phase != PhaseStopped || len(st.Services) > 0) {
				return fmt.Errorf("project %s is owned by %s; stop that stack or select another --project", s.Project, st.Root)
			}
		}
	}
	data, err = json.Marshal(projectOwner{StateDir: s.StateDir})
	if err != nil {
		return err
	}
	return writeFileAtomic(path, append(data, '\n'), 0o644)
}

type legacyState struct {
	Dir   string
	State *State
}

func (s *Stack) legacyStates() ([]legacyState, error) {
	common := filepath.Dir(s.StateDir)
	dirs, err := filepath.Glob(filepath.Join(common, "worktrees", "*", "ods-stack"))
	if err != nil {
		return nil, err
	}
	dirs = append(dirs, filepath.Join(common, "ods-stack"))
	var legacy []legacyState
	for _, dir := range dirs {
		st, err := (&Stack{StateDir: dir}).ReadState()
		if err != nil {
			return nil, err
		}
		if st != nil && st.Project != "" {
			st.Project = docker.NormalizeProjectName(st.Project)
			legacy = append(legacy, legacyState{Dir: dir, State: st})
		}
	}
	return legacy, nil
}

func (s *Stack) selectLegacyProject() error {
	legacy, err := s.legacyStates()
	if err != nil {
		return err
	}
	projects := map[string]bool{}
	for _, candidate := range legacy {
		projects[candidate.State.Project] = true
	}
	if !s.ProjectExplicit && len(projects) > 1 {
		var names []string
		for project := range projects {
			names = append(names, project)
		}
		sort.Strings(names)
		return fmt.Errorf("several existing dev datasets found: %s; select one with 'ods --project NAME stack up' (the choice is saved)", strings.Join(names, ", "))
	}
	if !s.ProjectExplicit {
		for project := range projects {
			s.Project = project
		}
	}
	for _, candidate := range legacy {
		st := candidate.State
		if st.Project == s.Project && len(st.Services) > 0 && st.Phase != PhaseStopped {
			return fmt.Errorf("existing project %s is managed by the legacy stack in %s; run 'ods stack stop --isolated' there before reusing its data", st.Project, st.Root)
		}
	}
	return nil
}

// releaseLegacyLeases drops the port leases of the stopped legacy isolated
// stacks of this repository when shared mode adopts their data. A stack
// with a live process group keeps every lease; one whose containers still
// run keeps its Compose host port leases.
func (s *Stack) releaseLegacyLeases() error {
	if s.Registry == nil {
		return nil
	}
	legacy, err := s.legacyStates()
	if err != nil {
		return err
	}
	for _, candidate := range legacy {
		st := candidate.State
		if st.Phase != PhaseStopped || st.Root == "" || anyGroupAlive(st.Services) {
			continue
		}
		if running, err := projectContainersRunning(st.Project); err != nil || running {
			if err := s.Registry.ReleaseNames(st.Root, appLeaseNames(st)); err != nil {
				return err
			}
			continue
		}
		if err := s.Registry.Release(st.Root); err != nil {
			return err
		}
	}
	return nil
}
