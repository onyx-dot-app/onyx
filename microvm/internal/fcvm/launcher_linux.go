//go:build linux

package fcvm

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"golang.org/x/sys/unix"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcapi/client/operations"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
)

// Proc is one jailed Firecracker process.
type Proc struct {
	ID    string
	pid   int
	start uint64
	pidfd int
	done  chan struct{}
	l     *Launcher

	// mu serializes Kill. reaped: the process exited and pidfd is closed.
	// killed: Kill succeeded, so later calls do nothing.
	mu     sync.Mutex
	reaped bool
	killed bool
}

// PID returns the host PID of Firecracker.
func (p *Proc) PID() int { return p.pid }

// Info implements agent.Process.
func (p *Proc) Info() agent.ProcInfo {
	lay := p.l.Cmd.Layout
	return agent.ProcInfo{
		PID: p.pid, PIDStart: p.start, Chroot: lay.ChrootDir(p.ID),
		APISock: lay.HostPath(p.ID, jailer.APISock), VsockUDS: lay.HostPath(p.ID, template.VsockUDS),
	}
}

// Done is closed when Firecracker has exited.
func (p *Proc) Done() <-chan struct{} { return p.done }

// API returns a client for the VM's Firecracker API socket.
func (p *Proc) API() *operations.Client {
	return APIClient(p.l.Cmd.Layout.HostPath(p.ID, jailer.APISock))
}

// Launch restores a VM from its template. It implements agent.Launcher.
func (l *Launcher) Launch(ctx context.Context, s agent.LaunchSpec) (agent.Process, error) {
	t := s.Template
	files := make([]FileSource, 0, len(t.FileList()))
	for _, f := range t.FileList() {
		fs := FileSource{Name: f, Src: t.Path(f)}
		if f == template.ScratchFile {
			fs.VMOwned, fs.Size = true, s.ScratchBytes
		}
		files = append(files, fs)
	}
	p, err := l.Spawn(ctx, s.ID, s.UID, files)
	if err != nil {
		return nil, err
	}
	// The copies share the blocks of the verified files only if no file
	// changed between the hash check and the copy.
	if err := t.CheckUnchanged(); err != nil {
		return nil, l.abort(p, err, nil)
	}
	api := p.API()
	if err := LoadSnapshot(ctx, api, "/"+template.VMStateFile, "/"+template.MemFile); err != nil {
		return nil, l.abort(p, err, nil)
	}
	if s.ScratchBytes > int64(t.ScratchGiB)*scratch.GiB {
		if err := RefreshDrive(ctx, api, template.ScratchDriveID, "/"+template.ScratchFile); err != nil {
			return nil, l.abort(p, err, nil)
		}
	}
	return p, nil
}

// Spawn prepares the chroot of VM id and starts Firecracker under the jailer
// in the host slice. Firecracker waits on its API socket when Spawn returns.
func (l *Launcher) Spawn(ctx context.Context, id string, uid uint32, files []FileSource) (*Proc, error) {
	lay := l.Cmd.Layout
	chroot := lay.ChrootDir(id)
	root := lay.RootDir(id)
	// A leftover chroot can belong to a VM that still runs. Never remove it here.
	if _, err := os.Lstat(chroot); err == nil {
		return nil, fmt.Errorf("chroot %s already exists", chroot)
	}
	if err := os.MkdirAll(root, 0o755); err != nil {
		return nil, err
	}
	// ok: the start worked. keep: the VM may still run, so its chroot stays.
	ok, keep := false, false
	defer func() {
		if !ok && !keep {
			_ = os.RemoveAll(chroot)
		}
	}()
	for _, f := range files {
		dst := filepath.Join(root, f.Name)
		if !f.VMOwned {
			if err := scratch.Clone(f.Src, dst, 0o644, 0, 0); err != nil {
				return nil, fmt.Errorf("copy %s: %w", f.Name, err)
			}
			continue
		}
		size := f.Size
		if size == 0 {
			st, err := os.Stat(f.Src)
			if err != nil {
				return nil, err
			}
			size = st.Size()
		}
		if err := scratch.Prepare(f.Src, dst, size, int(uid), int(uid)); err != nil {
			return nil, fmt.Errorf("copy %s: %w", f.Name, err)
		}
	}
	logPath := lay.HostPath(id, jailer.LogFile)
	if err := os.WriteFile(logPath, nil, 0o600); err != nil {
		return nil, err
	}
	if err := os.Chown(logPath, int(uid), int(uid)); err != nil {
		return nil, err
	}
	console, err := os.OpenFile(lay.ConsoleLog(id), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return nil, err
	}
	defer func() { _ = console.Close() }()

	argv, err := l.Cmd.Argv(id, uid)
	if err != nil {
		return nil, err
	}
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Stdout = console
	cmd.Stderr = console
	cmd.Env = []string{"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	// From here a Firecracker process may exist. Every failure must stop it,
	// or keep the chroot and report agent.ErrVMLeft.
	// With --new-pid-ns the jailer exits after it starts Firecracker.
	if err := cmd.Run(); err != nil {
		return nil, l.abortScope(id, fmt.Errorf("jailer: %w; console: %s", err, tail(lay.ConsoleLog(id))), &keep)
	}
	pid, err := readPID(lay.HostPath(id, jailer.PIDFile))
	if err != nil {
		return nil, l.abortScope(id, err, &keep)
	}
	pidfd, err := unix.PidfdOpen(pid, 0)
	if err != nil {
		return nil, l.abortScope(id, fmt.Errorf("pidfd_open %d: %w", pid, err), &keep)
	}
	p := &Proc{ID: id, pid: pid, pidfd: pidfd, done: make(chan struct{}), l: l}
	go p.watch()
	if err := l.checkProcess(ctx, id, pid); err != nil {
		return nil, l.abort(p, err, &keep)
	}
	if p.start, err = l.procStart(pid); err != nil {
		return nil, l.abort(p, err, &keep)
	}
	if err := WaitSocket(ctx, lay.HostPath(id, jailer.APISock)); err != nil {
		return nil, l.abort(p, fmt.Errorf("%w; fc.log: %s", err, tail(logPath)), &keep)
	}
	ok = true
	return p, nil
}

// checkProcess verifies that pid is our Firecracker in the VM scope. The
// jailer writes the PID file before its child execs Firecracker, so the comm
// can still be "jailer" for a moment.
func (l *Launcher) checkProcess(ctx context.Context, id string, pid int) error {
	for {
		comm, err := os.ReadFile(l.procFile(pid, "comm"))
		if err != nil {
			return err
		}
		c := strings.TrimSpace(string(comm))
		if c == jailer.ExecName {
			break
		}
		if c != "jailer" {
			return fmt.Errorf("pid %d is %q, not %s", pid, c, jailer.ExecName)
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("pid %d did not exec %s: %w", pid, jailer.ExecName, ctx.Err())
		case <-time.After(time.Millisecond):
		}
	}
	cg, err := os.ReadFile(l.procFile(pid, "cgroup"))
	if err != nil {
		return err
	}
	got, ok, err := l.Cgroups.vmScope(string(cg), l.Cmd.Slice, pid)
	if err != nil {
		return err
	}
	if !ok || got != id {
		return fmt.Errorf("pid %d is in cgroup %q, want %s/%s", pid, strings.TrimSpace(string(cg)), l.Cmd.Slice, jailer.ScopeUnit(id))
	}
	return nil
}

const abortTimeout = 30 * time.Second

// abort kills p after a failed start. If that fails, the VM may still run:
// it sets *keep, so Spawn keeps the chroot, and the error wraps
// agent.ErrVMLeft.
func (l *Launcher) abort(p *Proc, cause error, keep *bool) error {
	ctx, cancel := context.WithTimeout(context.Background(), abortTimeout)
	defer cancel()
	if err := p.Kill(ctx); err != nil {
		if keep != nil {
			*keep = true
		}
		return fmt.Errorf("%w (cleanup: %v): %w", cause, err, agent.ErrVMLeft)
	}
	return cause
}

// abortScope is abort for a failure before a Proc exists: it kills and
// stops the VM scope.
func (l *Launcher) abortScope(id string, cause error, keep *bool) error {
	ctx, cancel := context.WithTimeout(context.Background(), abortTimeout)
	defer cancel()
	if err := l.killScope(ctx, id); err != nil {
		*keep = true
		return fmt.Errorf("%w (cleanup: %v): %w", cause, err, agent.ErrVMLeft)
	}
	return cause
}

// killScope sends SIGKILL to every process in the VM scope and waits until
// the scope has stopped. A scope that is not loaded has no process.
func (l *Launcher) killScope(ctx context.Context, id string) error {
	unit := jailer.ScopeUnit(id)
	for _, args := range [][]string{{"kill", "--signal=SIGKILL", unit}, {"stop", unit}} {
		argv := l.Cmd.SystemctlArgv(args...)
		out, err := exec.CommandContext(ctx, argv[0], argv[1:]...).CombinedOutput()
		if err != nil && !bytes.Contains(out, []byte("not loaded")) {
			return fmt.Errorf("systemctl %s: %v: %s", args[0], err, bytes.TrimSpace(out))
		}
	}
	return nil
}

func (p *Proc) watch() {
	fds := []unix.PollFd{{Fd: int32(p.pidfd), Events: unix.POLLIN}}
	for {
		_, err := unix.Poll(fds, -1)
		if err == nil || !errors.Is(err, unix.EINTR) {
			break
		}
	}
	close(p.done)
}

// Kill sends SIGKILL, waits for the exit, stops the scope and removes the
// chroot. The guest has nothing to flush: the api_server saves the session
// before it calls Stop. A failed Kill can be retried; after a successful one,
// Kill does nothing.
func (p *Proc) Kill(ctx context.Context) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.killed {
		return nil
	}
	if err := p.kill(ctx); err != nil {
		return err
	}
	p.killed = true
	return nil
}

func (p *Proc) kill(ctx context.Context) error {
	if !p.reaped {
		if err := unix.PidfdSendSignal(p.pidfd, unix.SIGKILL, nil, 0); err != nil && !errors.Is(err, unix.ESRCH) {
			return fmt.Errorf("kill %d: %w", p.pid, err)
		}
		select {
		case <-p.done:
		case <-ctx.Done():
			return fmt.Errorf("pid %d did not exit: %w", p.pid, ctx.Err())
		}
		_ = unix.Close(p.pidfd)
		p.reaped = true
	}
	// The scope ends by itself when its last process exits. Stop it anyway in
	// case a process is left in it; "not loaded" is the normal result.
	argv := p.l.Cmd.SystemctlArgv("stop", "--no-block", jailer.ScopeUnit(p.ID))
	if out, err := exec.CommandContext(ctx, argv[0], argv[1:]...).CombinedOutput(); err != nil &&
		!bytes.Contains(out, []byte("not loaded")) {
		p.l.Log.Warn("stop scope", "unit", jailer.ScopeUnit(p.ID), "err", err, "out", string(out))
	}
	return os.RemoveAll(p.l.Cmd.Layout.ChrootDir(p.ID))
}

func readPID(path string) (int, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return 0, fmt.Errorf("read jailer pid file: %w", err)
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
	if err != nil || pid <= 1 {
		return 0, fmt.Errorf("bad jailer pid file %q", strings.TrimSpace(string(raw)))
	}
	return pid, nil
}

// ReplaceDrive implements agent.DriveReplacer. It puts a reflink copy of src
// (root-owned, mode 0644) at /<file> in the chroot and makes Firecracker
// open it for drive driveID (PATCH /drives). Firecracker reads the new size
// and tells the guest. The guest must not use the drive meanwhile.
func (p *Proc) ReplaceDrive(ctx context.Context, driveID, file, src string) error {
	if file == "" || strings.ContainsAny(file, "/\x00") || strings.HasPrefix(file, ".") {
		return fmt.Errorf("bad drive file name %q", file)
	}
	root := p.l.Cmd.Layout.RootDir(p.ID)
	tmp := filepath.Join(root, "."+file+".new")
	_ = os.Remove(tmp)
	if err := scratch.Clone(src, tmp, 0o644, 0, 0); err != nil {
		return fmt.Errorf("copy %s: %w", file, err)
	}
	if err := os.Rename(tmp, filepath.Join(root, file)); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	return RefreshDrive(ctx, p.API(), driveID, "/"+file)
}
