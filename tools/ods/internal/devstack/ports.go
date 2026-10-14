package devstack

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"sort"
	"syscall"
	"time"
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
// the current user. A lease belongs to a worktree root and a port name and
// survives restarts, so a worktree gets the same ports back.
type Registry struct {
	Dir string
}

// Lease records that root owns port for the service called Name.
type Lease struct {
	Port      int       `json:"port"`
	Root      string    `json:"root"`
	Name      string    `json:"name"`
	UpdatedAt time.Time `json:"updated_at"`
}

// PortRequest asks for one durable host port.
type PortRequest struct {
	// Name keys the lease, such as "web" or "POSTGRES_HOST_PORT".
	Name string
	// Preferred is the port scanned first when no lease exists.
	Preferred int
	// Fixed is a port already bound by this worktree's own running
	// container or process. It is recorded as is and not probed.
	Fixed int
}

type registryFile struct {
	Leases []Lease `json:"leases"`
}

// Lease assigns a host port to every request for root, under the registry
// lock. A request keeps its existing lease when the port is still free to
// bind (or Fixed), and otherwise moves to the next free port above Preferred.
// Leases of roots that no longer exist on disk are reclaimed.
func (r *Registry) Lease(root string, requests []PortRequest) (map[string]int, error) {
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

	// Ports leased to other worktrees are never offered to this one.
	foreign := map[int]bool{}
	mine := map[string]Lease{}
	for _, l := range leases {
		if l.Root == root {
			mine[l.Name] = l
		} else {
			foreign[l.Port] = true
		}
	}

	claimed := map[int]bool{}
	result := make(map[string]int, len(requests))
	now := time.Now().UTC()
	for _, req := range requests {
		port, err := choosePort(req, mine[req.Name].Port, foreign, claimed)
		if err != nil {
			return nil, err
		}
		claimed[port] = true
		result[req.Name] = port
		mine[req.Name] = Lease{Port: port, Root: root, Name: req.Name, UpdatedAt: now}
	}

	var updated []Lease
	for _, l := range leases {
		if l.Root != root {
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

// Release drops every lease root holds.
func (r *Registry) Release(root string) error {
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
		if l.Root != root {
			kept = append(kept, l)
		}
	}
	return r.write(kept)
}

// Leases returns every lease in the registry.
func (r *Registry) Leases() ([]Lease, error) {
	return r.read()
}

func choosePort(req PortRequest, current int, foreign, claimed map[int]bool) (int, error) {
	if req.Fixed > 0 {
		return req.Fixed, nil
	}
	if current > 0 && !claimed[current] && !neverLease[current] && !foreign[current] && bindable(current) {
		return current, nil
	}
	if req.Preferred <= 0 {
		return 0, fmt.Errorf("port %s: no preferred port", req.Name)
	}
	for port := req.Preferred; port < req.Preferred+maxScan && port <= 65535; port++ {
		if claimed[port] || neverLease[port] || foreign[port] {
			continue
		}
		if bindable(port) {
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
