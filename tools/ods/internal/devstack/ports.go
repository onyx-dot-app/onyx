package devstack

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

const (
	registryFileName = "ports.json"
	registryLockName = "ports.lock"
	// registryWait bounds the short critical section other worktrees hold.
	registryWait = 30 * time.Second
	// maxScan is how far above the preferred port a lease may land.
	maxScan = 1000
)

// neverLease holds ports a lease must not take. The Slack bot binds its
// metrics server to 8000 with no override, so the stack leaves it free.
var neverLease = map[int]bool{8000: true}

// Registry is the host-wide table of port leases, shared by every worktree of
// the current user. A lease belongs to an owner key (a worktree root for an
// isolated stack, the state directory otherwise) and a port name. A lease
// survives restarts only while its stack runs: stop releases the application
// leases, down releases every lease, and a stopped owner's leases can be
// reclaimed by another stack.
type Registry struct {
	Dir string
}

// Lease records that root owns port for the service called Name.
type Lease struct {
	Port int    `json:"port"`
	Root string `json:"root"`
	Name string `json:"name"`
	// StateDir is the owner's state directory, used to tell whether an
	// owner's stack is stopped. Older leases do not record it.
	StateDir  string    `json:"state_dir,omitempty"`
	UpdatedAt time.Time `json:"updated_at"`
}

// PortRequest asks for one durable host port.
type PortRequest struct {
	// Name keys the lease, such as "web" or "POSTGRES_HOST_PORT".
	Name string
	// Preferred is the port scanned first when no lease exists.
	Preferred int
	// Replace selects a new preferred port instead of retaining an old lease.
	Replace bool
	// Fixed is a port already bound by this worktree's own running
	// container or process. It is recorded as is and not probed.
	Fixed int
	// Running marks a port of a service that runs, so its lease does not
	// move down to a lower free port.
	Running bool
}

type registryFile struct {
	Leases []Lease `json:"leases"`
}

// LeaseFor assigns a host port to every request for root, under the registry
// lock, and records stateDir in its leases. A request keeps its existing
// lease when the port is still free to bind (or Fixed) and no lower free port
// is available, and otherwise moves to the lowest free port from Preferred.
// Leases of roots that no longer exist on disk are dropped, and leases of
// stopped stacks are reclaimed when their port is chosen.
func (r *Registry) LeaseFor(root, stateDir string, requests []PortRequest) (map[string]int, error) {
	if err := os.MkdirAll(r.Dir, 0o755); err != nil {
		return nil, err
	}
	release, err := r.lock()
	if err != nil {
		return nil, err
	}
	defer release()

	leases, err := r.read()
	if err != nil {
		return nil, err
	}
	leases = pruneStale(leases, root)

	// Ports leased to other live stacks are never offered to this one.
	foreignLeases := map[int][]Lease{}
	mine := map[string]Lease{}
	for _, l := range leases {
		if l.Root == root {
			mine[l.Name] = l
		} else {
			foreignLeases[l.Port] = append(foreignLeases[l.Port], l)
		}
	}
	reclaim := &reclaimer{states: map[string]*reclaimState{}, projects: map[string]bool{}}
	foreign := func(port int) bool {
		for _, l := range foreignLeases[port] {
			if !reclaim.abandoned(l) {
				return true
			}
		}
		return false
	}

	claimed := map[int]bool{}
	reclaimed := map[int]bool{}
	result := make(map[string]int, len(requests))
	now := time.Now().UTC()
	for _, req := range requests {
		port, err := choosePort(req, mine[req.Name].Port, foreign, claimed)
		if err != nil {
			return nil, err
		}
		if req.Fixed == 0 && len(foreignLeases[port]) > 0 {
			reclaimed[port] = true
		}
		claimed[port] = true
		result[req.Name] = port
		mine[req.Name] = Lease{Port: port, Root: root, Name: req.Name, StateDir: stateDir, UpdatedAt: now}
	}

	var updated []Lease
	for _, l := range leases {
		if l.Root != root && !reclaimed[l.Port] {
			updated = append(updated, l)
		}
	}
	for _, l := range mine {
		updated = append(updated, l)
	}
	sort.Slice(updated, func(i, j int) bool {
		if updated[i].Root != updated[j].Root {
			return updated[i].Root < updated[j].Root
		}
		return updated[i].Name < updated[j].Name
	})
	return result, r.write(updated)
}

// reclaimer decides whether another owner's lease is abandoned. It reads
// each owner's state and each Compose project at most once per Lease call.
type reclaimer struct {
	states   map[string]*reclaimState
	projects map[string]bool
}

type reclaimState struct {
	stopped bool
	project string
}

// abandoned reports whether l belongs to a stack that no longer uses it:
// the owner's state is stopped or missing, none of its recorded process
// groups is alive, and, for an infrastructure port, its Compose project has
// no running container.
func (c *reclaimer) abandoned(l Lease) bool {
	dir := l.StateDir
	if dir == "" {
		switch filepath.Base(l.Root) {
		case sharedStateDirName, frontendStateDirName:
			dir = l.Root
		default:
			return false
		}
	}
	state, ok := c.states[dir]
	if !ok {
		state = &reclaimState{}
		st, err := (&Stack{StateDir: dir}).ReadState()
		switch {
		case err != nil:
		case st == nil:
			state.stopped = true
		case st.Phase == PhaseStopped && !anyGroupAlive(st.Services):
			state.stopped, state.project = true, st.Project
		}
		c.states[dir] = state
	}
	if !state.stopped {
		return false
	}
	if !isInfraLease(l.Name) {
		return true
	}
	if state.project == "" {
		return false
	}
	running, ok := c.projects[state.project]
	if !ok {
		var err error
		running, err = projectContainersRunning(state.project)
		running = running || err != nil
		c.projects[state.project] = running
	}
	return !running
}

func anyGroupAlive(recs []ServiceRecord) bool {
	for _, rec := range recs {
		if rec.PGID > 1 && groupAlive(rec.PGID) {
			return true
		}
	}
	return false
}

// isInfraLease reports whether a lease name is a Compose host port.
func isInfraLease(name string) bool {
	return strings.HasSuffix(name, "_HOST_PORT")
}

// projectContainersRunning reports whether a Compose project has a running
// container. Tests replace it.
var projectContainersRunning = func(project string) (bool, error) {
	out, err := exec.Command("docker", "ps", "-q", "--filter", "label="+docker.ComposeProjectLabel+"="+project, "--filter", "status=running").Output()
	if err != nil {
		return false, err
	}
	return len(strings.Fields(string(out))) > 0, nil
}

// Release drops every lease root holds.
func (r *Registry) Release(root string) error {
	return r.release(root, nil)
}

// ReleaseNames drops the leases root holds for names.
func (r *Registry) ReleaseNames(root string, names []string) error {
	if len(names) == 0 {
		return nil
	}
	drop := make(map[string]bool, len(names))
	for _, name := range names {
		drop[name] = true
	}
	return r.release(root, drop)
}

// release drops root's leases for names, or all of them when names is nil.
func (r *Registry) release(root string, names map[string]bool) error {
	release, err := r.lock()
	if err != nil {
		return err
	}
	defer release()
	leases, err := r.read()
	if err != nil {
		return err
	}
	var kept []Lease
	for _, l := range leases {
		if l.Root != root || (names != nil && !names[l.Name]) {
			kept = append(kept, l)
		}
	}
	return r.write(kept)
}

// Leases returns every lease in the registry.
func (r *Registry) Leases() ([]Lease, error) {
	return r.read()
}

func choosePort(req PortRequest, current int, foreign func(int) bool, claimed map[int]bool) (int, error) {
	if req.Fixed > 0 {
		return req.Fixed, nil
	}
	free := func(port int) bool {
		return !claimed[port] && !neverLease[port] && !foreign(port) && bindable(port)
	}
	if !req.Replace && current > 0 {
		// A service that is not running moves down to a lower free port,
		// so leases drift back toward the preferred port.
		if !req.Running && req.Preferred > 0 && current > req.Preferred {
			for port := req.Preferred; port < current && port < req.Preferred+maxScan && port <= 65535; port++ {
				if free(port) {
					return port, nil
				}
			}
		}
		if free(current) {
			return current, nil
		}
	}
	if req.Preferred <= 0 {
		return 0, fmt.Errorf("port %s: no preferred port", req.Name)
	}
	for port := req.Preferred; port < req.Preferred+maxScan && port <= 65535; port++ {
		if free(port) {
			return port, nil
		}
	}
	return 0, fmt.Errorf("port %s: no free port in %d-%d", req.Name, req.Preferred, req.Preferred+maxScan-1)
}

// bindable reports whether the port can be bound on every interface.
func bindable(port int) bool {
	available := false
	for _, probe := range []struct{ network, host string }{
		{"tcp4", "127.0.0.1"}, {"tcp4", "0.0.0.0"},
		{"tcp6", "::1"}, {"tcp6", "::"},
	} {
		ln, err := net.Listen(probe.network, net.JoinHostPort(probe.host, fmt.Sprint(port)))
		if errors.Is(err, syscall.EAFNOSUPPORT) || errors.Is(err, syscall.EPROTONOSUPPORT) || errors.Is(err, syscall.EADDRNOTAVAIL) {
			continue
		}
		if err != nil {
			return false
		}
		_ = ln.Close()
		available = true
	}
	return available
}

func pruneStale(leases []Lease, root string) []Lease {
	exists := map[string]bool{root: true}
	var kept []Lease
	for _, l := range leases {
		ok, seen := exists[l.Root]
		if !seen {
			_, err := os.Stat(l.Root)
			ok = err == nil
			exists[l.Root] = ok
		}
		if ok {
			kept = append(kept, l)
		}
	}
	return kept
}

func (r *Registry) read() ([]Lease, error) {
	data, err := os.ReadFile(filepath.Join(r.Dir, registryFileName))
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var f registryFile
	if err := json.Unmarshal(data, &f); err != nil {
		return nil, fmt.Errorf("parse port registry: %w", err)
	}
	return f.Leases, nil
}

func (r *Registry) write(leases []Lease) error {
	data, err := json.MarshalIndent(registryFile{Leases: leases}, "", "  ")
	if err != nil {
		return err
	}
	return writeFileAtomic(filepath.Join(r.Dir, registryFileName), append(data, '\n'), 0o644)
}

func (r *Registry) lock() (func(), error) {
	if err := os.MkdirAll(r.Dir, 0o755); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Join(r.Dir, registryLockName), os.O_RDWR|os.O_CREATE, 0o644)
	if err != nil {
		return nil, err
	}
	deadline := time.Now().Add(registryWait)
	for {
		err := tryFlock(f)
		if err == nil {
			return func() { _ = unflock(f); _ = f.Close() }, nil
		}
		if !errors.Is(err, errWouldBlock) || time.Now().After(deadline) {
			_ = f.Close()
			if errors.Is(err, errWouldBlock) {
				err = fmt.Errorf("port registry busy for %s", registryWait)
			}
			return nil, err
		}
		time.Sleep(50 * time.Millisecond)
	}
}
