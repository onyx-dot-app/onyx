package cmd

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

func runtimeMode() devstack.Mode {
	if rootIsolated {
		return devstack.Isolated
	}
	return devstack.Shared
}

func resolveRuntimeTarget() (devstack.Target, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return devstack.Target{}, err
	}
	return devstack.ResolveTarget(cwd, flagProjectName(), runtimeMode())
}

func stackForTarget(target devstack.Target) *devstack.Stack {
	return &devstack.Stack{Root: target.Root, Project: target.Project, StateDir: target.StateDir, Mode: target.Mode,
		ProjectExplicit: flagProjectName() != "", Registry: runtimeRegistry()}
}

func runtimeRegistry() *devstack.Registry {
	return &devstack.Registry{Dir: filepath.Join(paths.DataDir(), "stack")}
}

func lockRuntimeTarget(target devstack.Target, mutating bool) (func(), error) {
	stack := stackForTarget(target)
	release, err := stack.Lock(context.Background(), "runtime target", 30*time.Second)
	if err != nil {
		return nil, err
	}
	releaseProject, err := stack.LockInfrastructure(context.Background(), 30*time.Second)
	if err != nil {
		release()
		return nil, err
	}
	if mutating {
		st, err := stack.ReadState()
		if err != nil {
			releaseProject()
			release()
			return nil, err
		}
		if err := validateRuntimeOwnership(target, st); err != nil {
			releaseProject()
			release()
			return nil, err
		}
	}
	return func() { releaseProject(); release() }, nil
}

func validateRuntimeOwnership(target devstack.Target, st *devstack.State) error {
	if !target.Managed && st != nil && st.Project == target.Project {
		return fmt.Errorf("project %s was claimed by %s after target selection; retry the command", target.Project, st.Root)
	}
	changed := target.Managed && (st == nil || st.Project != target.Project)
	foreign := st != nil && st.Project == target.Project && st.Root != target.Root
	if changed || foreign {
		owner := target.OwnerRoot
		if st != nil {
			owner = st.Root
		}
		return fmt.Errorf("project %s is managed by another checkout; run this command from %s", target.Project, owner)
	}
	return nil
}
