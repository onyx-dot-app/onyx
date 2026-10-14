// Package devstack runs the local Onyx dev stack for one worktree: it leases
// host ports, starts the application services as managed process groups,
// keeps their state in the worktree's git metadata, and reconciles a partial
// start on the next run.
package devstack

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
	"unicode"
)

const (
	stateFileName = "state.json"
	lockFileName  = "lock"
	logsDirName   = "logs"

	// SchemaVersion is bumped when State changes shape.
	SchemaVersion = 1
)

// Phases of a stack, as recorded in State.Phase.
const (
	PhasePreparing = "preparing"
	PhaseInfra     = "infra"
	PhaseMigrating = "migrating"
	PhaseStarting  = "starting"
	PhaseReady     = "ready"
	PhaseDegraded  = "degraded"
	PhaseStopped   = "stopped"
	PhaseFailed    = "failed"
)

// Stack identifies one worktree's dev stack.
type Stack struct {
	// Root is the worktree root with symlinks resolved.
	Root string
	// StateDir holds the state file, lock and logs. It lives in the
	// worktree's git metadata so every agent in the worktree shares it.
	StateDir string
	// Project is the Docker Compose project name.
	Project string
	// Registry holds the host-wide port leases.
	Registry *Registry
}

// Open resolves the stack for the worktree that contains dir. project
// overrides the derived Compose project name when not empty.
func Open(dir, project string) (*Stack, error) {
	root, err := gitOutput(dir, "rev-parse", "--show-toplevel")
	if err != nil {
		return nil, fmt.Errorf("%s is not inside a git worktree: %w", dir, err)
	}
	if root, err = filepath.EvalSymlinks(root); err != nil {
		return nil, err
	}
	stateDir, err := gitOutput(root, "rev-parse", "--git-path", "ods-stack")
	if err != nil {
		return nil, err
	}
	if !filepath.IsAbs(stateDir) {
		stateDir = filepath.Join(root, stateDir)
	}
	if project == "" {
		project = ProjectName(root)
	}
	return &Stack{Root: root, StateDir: stateDir, Project: project}, nil
}

// ProjectName derives a Compose project name that is unique per worktree
// path: the normalized directory name plus a short hash of the full path.
func ProjectName(root string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(filepath.Base(root)) {
		if unicode.IsLetter(r) || unicode.IsDigit(r) || r == '-' || r == '_' {
			b.WriteRune(r)
		}
	}
	name := strings.Trim(b.String(), "-_")
	if name == "" {
		name = "onyx"
	}
	if len(name) > 40 {
		name = name[:40]
	}
	sum := sha256.Sum256([]byte(root))
	return name + "-" + hex.EncodeToString(sum[:])[:8]
}

func gitOutput(dir string, args ...string) (string, error) {
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	out, err := cmd.Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(out)), nil
}

// State is the persisted record of a stack.
type State struct {
	SchemaVersion int               `json:"schema_version"`
	Root          string            `json:"root"`
	Project       string            `json:"project"`
	Profile       string            `json:"profile"`
	Phase         string            `json:"phase"`
	Ports         map[string]int    `json:"ports"`
	Services      []ServiceRecord   `json:"services"`
	Errors        []string          `json:"errors,omitempty"`
	UpdatedAt     time.Time         `json:"updated_at"`
	Extra         map[string]string `json:"extra,omitempty"`
}

// ReadState returns the persisted state, or nil when the stack has none.
func (s *Stack) ReadState() (*State, error) {
	data, err := os.ReadFile(filepath.Join(s.StateDir, stateFileName))
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var st State
	if err := json.Unmarshal(data, &st); err != nil {
		return nil, fmt.Errorf("parse %s: %w", filepath.Join(s.StateDir, stateFileName), err)
	}
	return &st, nil
}

// WriteState persists st atomically.
func (s *Stack) WriteState(st *State) error {
	st.SchemaVersion = SchemaVersion
	st.Root = s.Root
	st.Project = s.Project
	st.UpdatedAt = time.Now().UTC()
	if st.Ports == nil {
		st.Ports = map[string]int{}
	}
	if err := os.MkdirAll(s.StateDir, 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(st, "", "  ")
	if err != nil {
		return err
	}
	return writeFileAtomic(filepath.Join(s.StateDir, stateFileName), append(data, '\n'), 0o644)
}

// LogDir is where service logs are written.
func (s *Stack) LogDir() string {
	return filepath.Join(s.StateDir, logsDirName)
}

func writeFileAtomic(path string, data []byte, perm os.FileMode) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), "."+filepath.Base(path)+".tmp-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer func() { _ = os.Remove(tmpName) }()
	_, writeErr := tmp.Write(data)
	closeErr := tmp.Close()
	if err := errors.Join(writeErr, closeErr); err != nil {
		return err
	}
	if err := os.Chmod(tmpName, perm); err != nil {
		return err
	}
	return os.Rename(tmpName, path)
}
