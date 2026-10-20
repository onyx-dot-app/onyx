package devstack

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

type Target struct {
	Root      string
	Project   string
	OwnerRoot string
	StateDir  string
	Mode      Mode
	Ports     map[string]int
	Managed   bool
}

func ResolveTarget(dir, project string, mode Mode) (Target, error) {
	stack, err := Open(dir, project, mode)
	if err != nil {
		return Target{}, err
	}
	return resolveOpenedTarget(stack, project != "")
}

func resolveOpenedTarget(stack *Stack, explicit bool) (Target, error) {
	target := Target{Root: stack.Root, Project: stack.Project, StateDir: stack.StateDir, Mode: stack.Mode, Ports: map[string]int{}}
	st, err := stack.ReadState()
	if err != nil {
		return Target{}, err
	}
	if st != nil && docker.NormalizeProjectName(st.Project) == target.Project {
		return target.withState(st), nil
	}
	if st != nil && !explicit {
		return Target{}, fmt.Errorf("selected project changed during target resolution; retry the command")
	}
	if stack.Mode != Shared {
		return target, nil
	}
	legacy, err := stack.legacyStates()
	if err != nil {
		return Target{}, err
	}
	projects := map[string]bool{}
	for _, candidate := range legacy {
		projects[docker.NormalizeProjectName(candidate.State.Project)] = true
	}
	if !explicit && len(projects) > 1 {
		names := make([]string, 0, len(projects))
		for name := range projects {
			names = append(names, name)
		}
		sort.Strings(names)
		return Target{}, fmt.Errorf("several existing dev datasets found: %s; select one with --project NAME", strings.Join(names, ", "))
	}
	if !explicit {
		for name := range projects {
			target.Project = name
		}
	}
	var selected *legacyState
	for i := range legacy {
		candidate := &legacy[i]
		if docker.NormalizeProjectName(candidate.State.Project) != target.Project {
			continue
		}
		active := candidate.State.Phase != PhaseStopped && len(candidate.State.Services) > 0
		if selected != nil && selected.State.Phase != PhaseStopped && len(selected.State.Services) > 0 {
			if active {
				return Target{}, fmt.Errorf("project %s has several managed owners; stop the extra stacks before continuing", target.Project)
			}
			continue
		}
		if selected == nil || active {
			selected = candidate
		}
	}
	if selected != nil {
		target.Mode, target.StateDir = Isolated, selected.Dir
		return target.withState(selected.State), nil
	}
	return target, nil
}

func (t Target) withState(st *State) Target {
	t.Managed = true
	t.OwnerRoot = st.Root
	for name, port := range st.Ports {
		t.Ports[name] = port
	}
	return t
}

func ResolveManagedDatabaseTarget(dir string, port int, registry *Registry) (Target, bool, error) {
	if port <= 0 || port > 65535 {
		return Target{}, false, fmt.Errorf("invalid database port %d", port)
	}
	shared, err := Open(dir, "", Shared)
	if err != nil {
		return Target{}, false, err
	}
	st, err := shared.ReadState()
	if err != nil {
		return Target{}, false, err
	}
	legacy, err := shared.legacyStates()
	if err != nil {
		return Target{}, false, err
	}
	type candidate struct {
		dir   string
		mode  Mode
		state *State
	}
	var candidates []candidate
	if st != nil && st.Project != "" {
		candidates = append(candidates, candidate{dir: shared.StateDir, mode: Shared, state: st})
	}
	for _, old := range legacy {
		if st == nil || old.State.Project != st.Project {
			candidates = append(candidates, candidate{dir: old.Dir, mode: Isolated, state: old.State})
		}
	}
	if registry != nil {
		paths, err := filepath.Glob(filepath.Join(registry.Dir, "projects", "*", "owner.json"))
		if err != nil {
			return Target{}, false, err
		}
		seen := map[string]bool{}
		for _, candidate := range candidates {
			seen[candidate.dir] = true
		}
		for _, path := range paths {
			data, err := os.ReadFile(path)
			if err != nil {
				return Target{}, false, err
			}
			var owner projectOwner
			if err := json.Unmarshal(data, &owner); err != nil {
				return Target{}, false, fmt.Errorf("parse project owner %s: %w", path, err)
			}
			if owner.StateDir == "" || !filepath.IsAbs(owner.StateDir) {
				return Target{}, false, fmt.Errorf("invalid project owner %s", path)
			}
			state, err := (&Stack{StateDir: owner.StateDir}).ReadState()
			if err != nil {
				return Target{}, false, err
			}
			if state == nil || state.Project == "" || filepath.Base(filepath.Dir(path)) != ProjectName(state.Project) {
				continue
			}
			kept := candidates[:0]
			for _, prior := range candidates {
				if prior.state.Project == state.Project && prior.dir != owner.StateDir {
					delete(seen, prior.dir)
					continue
				}
				kept = append(kept, prior)
			}
			candidates = kept
			if seen[owner.StateDir] {
				continue
			}
			mode := Isolated
			if filepath.Base(owner.StateDir) == "ods-stack-shared" {
				mode = Shared
			}
			candidates = append(candidates, candidate{dir: owner.StateDir, mode: mode, state: state})
			seen[owner.StateDir] = true
		}
	}
	var target Target
	found := false
	for _, candidate := range candidates {
		knownPort := candidate.state.Ports["POSTGRES_HOST_PORT"]
		actual, err := docker.GetHostPort(docker.ContainerName(candidate.state.Project, "relational_db"), 5432)
		if err == nil {
			knownPort = actual
		}
		if knownPort != port {
			continue
		}
		if found {
			return Target{}, false, fmt.Errorf("database port %d has several managed owners; resolve their infrastructure before migrating", port)
		}
		target = (Target{Root: shared.Root, Project: candidate.state.Project, StateDir: candidate.dir, Mode: candidate.mode, Ports: map[string]int{}}).withState(candidate.state)
		target.Ports["POSTGRES_HOST_PORT"] = knownPort
		found = true
	}
	return target, found, nil
}

func (t Target) Environment() ([]string, error) {
	fileEnv, err := LoadEnvFile(filepath.Join(t.Root, ".vscode", ".env"))
	if err != nil {
		return nil, err
	}
	env, err := t.ServiceEnv()
	if err != nil {
		return nil, err
	}
	return env.With(fileEnv), nil
}

func (t Target) ServiceEnv() (Env, error) {
	ports := make(map[string]int, len(t.Ports))
	for name, port := range t.Ports {
		ports[name] = port
	}
	for _, service := range docker.InfraServices {
		for _, spec := range service.Ports {
			if ports[spec.ComposeVar] > 0 {
				continue
			}
			if port, err := docker.GetHostPort(docker.ContainerName(t.Project, service.Name), spec.ContainerPort); err == nil {
				ports[spec.ComposeVar] = port
			}
		}
	}
	return HostServiceEnv(ports), nil
}

func HostServiceEnv(ports map[string]int) Env {
	overrides := map[string]string{}
	for _, service := range docker.InfraServices {
		for _, spec := range service.Ports {
			port := ports[spec.ComposeVar]
			if port <= 0 {
				continue
			}
			if spec.AppVar != "" {
				overrides[spec.AppVar] = spec.AppValue(port)
			}
			switch service.Name {
			case "relational_db":
				overrides["POSTGRES_HOST"] = "localhost"
			case "cache":
				overrides["REDIS_HOST"] = "localhost"
			case "opensearch":
				overrides["OPENSEARCH_HOST"] = "localhost"
			case "inference_model_server":
				overrides["MODEL_SERVER_HOST"] = "localhost"
				overrides["INDEXING_MODEL_SERVER_HOST"] = "localhost"
				overrides["INDEXING_MODEL_SERVER_PORT"] = fmt.Sprint(port)
			}
		}
	}
	if port := ports["web"]; port > 0 {
		overrides["PORT"] = fmt.Sprint(port)
		overrides["WEB_DOMAIN"] = fmt.Sprintf("http://localhost:%d", port)
	}
	if port := ports["api"]; port > 0 {
		overrides["INTERNAL_URL"] = fmt.Sprintf("http://localhost:%d", port)
	}
	if port := ports["mcp"]; port > 0 {
		overrides["MCP_SERVER_PORT"] = fmt.Sprint(port)
		overrides["MCP_INTERNAL_URL"] = fmt.Sprintf("http://localhost:%d", port)
	}
	if port := ports["model"]; port > 0 {
		overrides["MODEL_SERVER_HOST"] = "localhost"
		overrides["INDEXING_MODEL_SERVER_HOST"] = "localhost"
		overrides["MODEL_SERVER_PORT"] = fmt.Sprint(port)
		overrides["INDEXING_MODEL_SERVER_PORT"] = fmt.Sprint(port)
	}
	base := os.Environ()
	return Env{Base: base, Overrides: MergeEnv(base, mapToEnv(overrides))}
}
