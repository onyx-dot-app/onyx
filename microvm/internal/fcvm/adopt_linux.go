//go:build linux

package fcvm

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/unix"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/journal"
)

// Adopt implements agent.Adopter. The PID must still be our Firecracker:
// same start time, comm "firecracker", the VM scope as its cgroup (in any
// cgroup namespace, see CgroupView) and
// "--id <sandbox_id>" on its command line. Then GET / on its API socket must
// report "Running".
func (l *Launcher) Adopt(ctx context.Context, r journal.Record) (agent.Process, error) {
	if r.Chroot != l.Cmd.Layout.ChrootDir(r.SandboxID) {
		return nil, fmt.Errorf("journaled chroot %q is not the layout path %q", r.Chroot, l.Cmd.Layout.ChrootDir(r.SandboxID))
	}
	if r.PID <= 1 {
		return nil, fmt.Errorf("journaled pid %d", r.PID)
	}
	pidfd, err := unix.PidfdOpen(r.PID, 0)
	if errors.Is(err, unix.ESRCH) {
		return nil, agent.ErrGone
	}
	if err != nil {
		return nil, fmt.Errorf("pidfd_open %d: %w", r.PID, err)
	}
	// From here pidfd pins the process: if the checks pass, it is the VM.
	if err := l.verify(r.SandboxID, r.PID, r.PIDStart); err != nil {
		_ = unix.Close(pidfd)
		return nil, err
	}
	p := &Proc{ID: r.SandboxID, pid: r.PID, start: r.PIDStart, pidfd: pidfd, done: make(chan struct{}), l: l}
	go p.watch()
	actx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	state, err := State(actx, p.API())
	if err != nil || state != "Running" {
		return p, fmt.Errorf("%w: state %q: %v", agent.ErrAPINotResponding, state, err)
	}
	return p, nil
}

// verify checks that pid is the Firecracker of VM id. A mismatch means the
// VM is gone and the PID was reused.
func (l *Launcher) verify(id string, pid int, start uint64) error {
	got, err := l.procStart(pid)
	if errors.Is(err, os.ErrNotExist) {
		return agent.ErrGone
	}
	if err != nil {
		return err
	}
	if start != 0 && got != start {
		return fmt.Errorf("%w: pid %d start time %d, journal has %d", agent.ErrGone, pid, got, start)
	}
	matchID, ok, err := l.matchLayout(pid)
	if errors.Is(err, os.ErrNotExist) {
		return agent.ErrGone
	}
	if err != nil {
		return err
	}
	if !ok || matchID != id {
		return fmt.Errorf("%w: pid %d is not the Firecracker of %s", agent.ErrGone, pid, id)
	}
	return nil
}

func (l *Launcher) procRoot() string {
	if l.ProcFS == "" {
		return "/proc"
	}
	return l.ProcFS
}

// procFile is the path of a file in /proc/<pid>/.
func (l *Launcher) procFile(pid int, name string) string {
	return filepath.Join(l.procRoot(), strconv.Itoa(pid), name)
}

// gone reports whether a /proc read error means that the process exited.
func gone(err error) bool { return errors.Is(err, os.ErrNotExist) || errors.Is(err, unix.ESRCH) }

// matchLayout reports whether pid is a Firecracker in our layout, and its VM id.
func (l *Launcher) matchLayout(pid int) (string, bool, error) {
	comm, err := os.ReadFile(l.procFile(pid, "comm"))
	if err != nil {
		return "", false, err
	}
	if strings.TrimSpace(string(comm)) != jailer.ExecName {
		return "", false, nil
	}
	cg, err := os.ReadFile(l.procFile(pid, "cgroup"))
	if err != nil {
		return "", false, err
	}
	id, ok, err := l.Cgroups.vmScope(string(cg), l.Cmd.Slice, pid)
	if err != nil || !ok {
		return "", false, err
	}
	raw, err := os.ReadFile(l.procFile(pid, "cmdline"))
	if err != nil {
		return "", false, err
	}
	args := strings.Split(strings.TrimRight(string(raw), "\x00"), "\x00")
	for i := 0; i+1 < len(args); i++ {
		if args[i] == "--id" && args[i+1] == id {
			return id, true, nil
		}
	}
	return "", false, nil
}

// Scan implements agent.Adopter: every Firecracker process in our layout,
// with its UID, and every chroot without such a process. A process that
// exits during the scan is skipped; any other read error fails the scan.
func (l *Launcher) Scan() ([]agent.Candidate, error) {
	ents, err := os.ReadDir(l.procRoot())
	if err != nil {
		return nil, err
	}
	var out []agent.Candidate
	seen := map[string]bool{}
	for _, e := range ents {
		pid, convErr := strconv.Atoi(e.Name())
		if convErr != nil || pid <= 1 {
			continue
		}
		id, ok, matchErr := l.matchLayout(pid)
		if gone(matchErr) {
			continue
		}
		if matchErr != nil {
			return nil, fmt.Errorf("pid %d: %w", pid, matchErr)
		}
		if !ok {
			continue
		}
		uid, uidErr := l.procUID(pid)
		if gone(uidErr) {
			continue
		}
		if uidErr != nil {
			return nil, fmt.Errorf("pid %d: %w", pid, uidErr)
		}
		out = append(out, agent.Candidate{ID: id, PID: pid, UID: uid})
		seen[id] = true
	}
	dir := filepath.Join(l.Cmd.Layout.ChrootBase, jailer.ExecName)
	chroots, err := os.ReadDir(dir)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	for _, c := range chroots {
		if c.IsDir() && jailer.ValidID(c.Name()) && !seen[c.Name()] {
			out = append(out, agent.Candidate{ID: c.Name()})
		}
	}
	return out, nil
}

// Remove implements agent.Adopter: it checks the candidate again, kills it,
// stops its scope and removes its chroot.
func (l *Launcher) Remove(ctx context.Context, c agent.Candidate) error {
	if !jailer.ValidID(c.ID) {
		return fmt.Errorf("invalid VM id %q", c.ID)
	}
	if c.PID != 0 {
		pidfd, err := unix.PidfdOpen(c.PID, 0)
		if err != nil && !errors.Is(err, unix.ESRCH) {
			return err
		}
		if err == nil {
			// pidfd pins the process. Kill only after a check that worked.
			id, ok, mErr := l.matchLayout(c.PID)
			switch {
			case gone(mErr):
				_ = unix.Close(pidfd)
			case mErr != nil:
				_ = unix.Close(pidfd)
				return fmt.Errorf("check pid %d: %w", c.PID, mErr)
			case !ok || id != c.ID:
				_ = unix.Close(pidfd)
				return fmt.Errorf("pid %d is no longer the Firecracker of %s", c.PID, c.ID)
			default:
				p := &Proc{ID: c.ID, pid: c.PID, pidfd: pidfd, done: make(chan struct{}), l: l}
				go p.watch()
				return p.Kill(ctx)
			}
		}
	}
	// No process: stop the scope (it kills anything left in it) and remove the files.
	argv := l.Cmd.SystemctlArgv("stop", jailer.ScopeUnit(c.ID))
	if out, err := exec.CommandContext(ctx, argv[0], argv[1:]...).CombinedOutput(); err != nil &&
		!strings.Contains(string(out), "not loaded") {
		return fmt.Errorf("stop scope: %v: %s", err, strings.TrimSpace(string(out)))
	}
	return os.RemoveAll(l.Cmd.Layout.ChrootDir(c.ID))
}

// procUID returns the real UID of pid.
func (l *Launcher) procUID(pid int) (uint32, error) {
	raw, err := os.ReadFile(l.procFile(pid, "status"))
	if err != nil {
		return 0, err
	}
	for _, line := range strings.Split(string(raw), "\n") {
		if f := strings.Fields(line); len(f) >= 2 && f[0] == "Uid:" {
			uid, err := strconv.ParseUint(f[1], 10, 32)
			return uint32(uid), err
		}
	}
	return 0, fmt.Errorf("no Uid line in %s", l.procFile(pid, "status"))
}

// procStart returns the start time of pid (field 22 of /proc/<pid>/stat).
func (l *Launcher) procStart(pid int) (uint64, error) {
	raw, err := os.ReadFile(l.procFile(pid, "stat"))
	if err != nil {
		return 0, err
	}
	// comm (field 2) is in parentheses and can hold spaces.
	s := string(raw)
	i := strings.LastIndexByte(s, ')')
	if i < 0 {
		return 0, fmt.Errorf("bad /proc/%d/stat", pid)
	}
	f := strings.Fields(s[i+1:])
	// f[0] is field 3 (state), so field 22 is f[19].
	if len(f) < 20 {
		return 0, fmt.Errorf("short /proc/%d/stat", pid)
	}
	return strconv.ParseUint(f[19], 10, 64)
}
