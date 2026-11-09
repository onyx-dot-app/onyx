package fcvm

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
)

// CgroupView says how the agent reads the cgroup of a VM process.
//
// /proc/<pid>/cgroup shows a path relative to the reader's cgroup namespace
// root. In the host namespace a VM reads "0::/<slice>/fcvm-<id>.scope". A
// Kubernetes pod has its own cgroup namespace, so the same VM reads
// "0::/../../<slice>/fcvm-<id>.scope" there: the number of ".." steps
// depends on where the pod's cgroup is. In that case the agent confirms the
// match in the host's cgroup tree (ENG-4610).
type CgroupView struct {
	// Private is true when the agent's cgroup namespace is not the host's.
	Private bool
	// HostCgroupFS is the host's cgroup2 mount seen through the host's root
	// (/proc/1/root/sys/fs/cgroup; needs hostPID). Used only when Private.
	HostCgroupFS string
}

// DetectCgroupView compares the agent's cgroup namespace with the one of
// PID 1 (the host's init with hostPID). In a private namespace the host's
// cgroup tree must be readable, or the agent cannot verify its VMs and
// refuses to start.
func DetectCgroupView(procFS string) (CgroupView, error) {
	self, err := os.Readlink(filepath.Join(procFS, "self", "ns", "cgroup"))
	if err != nil {
		return CgroupView{}, fmt.Errorf("read own cgroup namespace: %w", err)
	}
	host, err := os.Readlink(filepath.Join(procFS, "1", "ns", "cgroup"))
	if err != nil {
		return CgroupView{}, fmt.Errorf("read the cgroup namespace of PID 1 (needs hostPID): %w", err)
	}
	if self == host {
		return CgroupView{}, nil
	}
	v := CgroupView{Private: true, HostCgroupFS: filepath.Join(procFS, "1", "root", "sys", "fs", "cgroup")}
	if _, err := os.Stat(filepath.Join(v.HostCgroupFS, "cgroup.controllers")); err != nil {
		return CgroupView{}, fmt.Errorf("the agent runs in its own cgroup namespace and cannot read the host cgroup tree at %s: %w",
			v.HostCgroupFS, err)
	}
	return v, nil
}

// scopeID parses a /proc/<pid>/cgroup body. It returns the VM id if the
// process is in a VM scope of slice, as seen from this view. In a private
// view the path must leave the namespace root ("/../"); the caller then
// confirms it in the host tree.
func (v CgroupView) scopeID(body, slice string) (string, bool) {
	line := strings.TrimSpace(body)
	if strings.Contains(line, "\n") || !strings.HasPrefix(line, "0::/") {
		return "", false
	}
	p := strings.TrimPrefix(line, "0::")
	if v.Private {
		up := 0
		for strings.HasPrefix(p, "/../") {
			p = p[len("/.."):]
			up++
		}
		if up == 0 {
			// Inside the pod's own cgroup: not a host VM scope.
			return "", false
		}
	}
	prefix := "/" + slice + "/fcvm-"
	if !strings.HasPrefix(p, prefix) || !strings.HasSuffix(p, ".scope") {
		return "", false
	}
	id := strings.TrimSuffix(strings.TrimPrefix(p, prefix), ".scope")
	if !jailer.ValidID(id) {
		return "", false
	}
	return id, true
}

// inHostScope reports whether pid is listed in the host's VM scope of id.
// A missing scope means the process has exited (os.ErrNotExist).
func (v CgroupView) inHostScope(slice, id string, pid int) (bool, error) {
	f, err := os.Open(filepath.Join(v.HostCgroupFS, slice, jailer.ScopeUnit(id), "cgroup.procs"))
	if err != nil {
		return false, err
	}
	defer func() { _ = f.Close() }()
	want := strconv.Itoa(pid)
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		if strings.TrimSpace(sc.Text()) == want {
			return true, nil
		}
	}
	return false, sc.Err()
}

// vmScope returns the VM id of the scope that pid is in, from the cgroup
// file body. ok is false if pid is not in one of our VM scopes. An error
// means that the check could not be done: the caller must not act on pid.
func (v CgroupView) vmScope(body, slice string, pid int) (string, bool, error) {
	id, ok := v.scopeID(body, slice)
	if !ok {
		return "", false, nil
	}
	if !v.Private {
		return id, true, nil
	}
	in, err := v.inHostScope(slice, id, pid)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return "", false, fmt.Errorf("host scope of %s: %w", id, err)
		}
		return "", false, fmt.Errorf("read host scope of %s: %w", id, err)
	}
	return id, in, nil
}
