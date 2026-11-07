package execs

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

// Cgroups puts each execution in its own cgroup v2 under Root
// (for example /sys/fs/cgroup/guestd). Kill uses cgroup.kill, so it also
// stops processes that left the session or process group.
type Cgroups struct {
	Root string
}

// NewCgroups checks that root's parent is cgroup v2, creates root and kills
// every leftover execution cgroup in it (from an earlier daemon process).
// It fails if a leftover cgroup cannot be killed and removed: its commands
// would then run on with no deadline. The VM init restarts the daemon, which
// tries again.
func NewCgroups(root string) (*Cgroups, error) {
	var st unix.Statfs_t
	if err := unix.Statfs(filepath.Dir(root), &st); err != nil {
		return nil, err
	}
	if st.Type != unix.CGROUP2_SUPER_MAGIC {
		return nil, fmt.Errorf("%s is not a cgroup v2 file system", filepath.Dir(root))
	}
	if err := os.MkdirAll(root, 0o755); err != nil {
		return nil, err
	}
	ents, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}
	var errs []error
	for _, e := range ents {
		if !e.IsDir() {
			continue
		}
		g := &cgroup{dir: filepath.Join(root, e.Name()), fd: -1}
		// cgroup.kill also kills the processes in child cgroups.
		if err := g.Kill(); err != nil {
			errs = append(errs, fmt.Errorf("kill leftover %s: %w", g.dir, err))
			continue
		}
		if err := g.Close(); err != nil {
			errs = append(errs, fmt.Errorf("remove leftover %s: %w", g.dir, err))
		}
	}
	if err := errors.Join(errs...); err != nil {
		return nil, err
	}
	return &Cgroups{Root: root}, nil
}

// NewGroup implements Isolator.
func (c *Cgroups) NewGroup(id string) (Group, error) {
	dir := filepath.Join(c.Root, id)
	if err := os.Mkdir(dir, 0o755); err != nil {
		return nil, err
	}
	fd, err := unix.Open(dir, unix.O_RDONLY|unix.O_DIRECTORY|unix.O_CLOEXEC, 0)
	if err != nil {
		_ = os.Remove(dir)
		return nil, err
	}
	return &cgroup{dir: dir, fd: fd}, nil
}

type cgroup struct {
	dir string
	fd  int
}

func (g *cgroup) Prepare(cmd *exec.Cmd) {
	// clone3(CLONE_INTO_CGROUP): the process starts inside the cgroup.
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true, UseCgroupFD: true, CgroupFD: g.fd}
}

func (g *cgroup) Started(int) {}

func (g *cgroup) Kill() error {
	err := os.WriteFile(filepath.Join(g.dir, "cgroup.kill"), []byte("1"), 0)
	if err == nil {
		return nil
	}
	// Kernels before 5.14 have no cgroup.kill.
	pids, rerr := g.pids()
	if rerr != nil {
		return errors.Join(err, rerr)
	}
	for _, p := range pids {
		_ = unix.Kill(p, unix.SIGKILL)
	}
	return nil
}

// Close waits until the cgroup is empty (up to 5 s), then removes it and
// every child cgroup that a command made in it, deepest first.
func (g *cgroup) Close() error {
	if g.fd >= 0 {
		_ = unix.Close(g.fd)
		g.fd = -1
	}
	deadline := time.Now().Add(5 * time.Second)
	for {
		err := removeTree(g.dir)
		if err == nil || errors.Is(err, unix.ENOENT) {
			return nil
		}
		if !errors.Is(err, unix.EBUSY) || time.Now().After(deadline) {
			return err
		}
		_ = g.Kill()
		time.Sleep(10 * time.Millisecond)
	}
}

// removeTree removes the cgroup dir and its child cgroups, deepest first.
// rmdir of a cgroup fails with EBUSY while it has children or processes.
func removeTree(dir string) error {
	ents, err := os.ReadDir(dir)
	if err != nil {
		return err
	}
	for _, e := range ents {
		if !e.IsDir() {
			continue
		}
		if err := removeTree(filepath.Join(dir, e.Name())); err != nil && !errors.Is(err, unix.ENOENT) {
			return err
		}
	}
	return unix.Rmdir(dir)
}

func (g *cgroup) pids() ([]int, error) {
	raw, err := os.ReadFile(filepath.Join(g.dir, "cgroup.procs"))
	if err != nil {
		return nil, err
	}
	var out []int
	sc := bufio.NewScanner(bytes.NewReader(raw))
	for sc.Scan() {
		if p, err := strconv.Atoi(sc.Text()); err == nil {
			out = append(out, p)
		}
	}
	return out, nil
}
