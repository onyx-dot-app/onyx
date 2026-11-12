package execs

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

// newTestCgroups needs root and cgroup v2 at /sys/fs/cgroup.
func newTestCgroups(t *testing.T) *Cgroups {
	t.Helper()
	var st unix.Statfs_t
	if os.Geteuid() != 0 || unix.Statfs("/sys/fs/cgroup", &st) != nil || st.Type != unix.CGROUP2_SUPER_MAGIC {
		t.Skip("needs root and cgroup v2")
	}
	var b [4]byte
	_, _ = rand.Read(b[:])
	root := "/sys/fs/cgroup/guestd-test-" + hex.EncodeToString(b[:])
	cg, err := NewCgroups(root)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Remove(root) })
	return cg
}

// startDetached starts a command whose child leaves the session (setsid),
// and returns the child's PID.
func startDetached(t *testing.T, m *Manager, deadline time.Duration) (*Execution, int) {
	t.Helper()
	// The child prints its PID after setsid, so it has left the session and
	// the process group before the test acts on it.
	return startPID(t, m, "setsid sh -c 'echo $$; exec sleep 100' & sleep 100", deadline)
}

// startPID starts script, which must print one PID line, and returns that PID.
func startPID(t *testing.T, m *Manager, script string, deadline time.Duration) (*Execution, int) {
	t.Helper()
	e, err := m.Start(Spec{Argv: []string{"sh", "-c", script}, Env: []string{"PATH=/usr/bin:/bin"}, Deadline: deadline})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _, _ = m.Cancel(context.Background(), e.ID)
	})
	for {
		// Take the channel before Read, so output between the two is not missed.
		ch := e.Changed()
		data, _, _ := e.Read(Stdout, 0, 64)
		if strings.HasSuffix(string(data), "\n") {
			pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
			if err != nil {
				t.Fatal(err)
			}
			return e, pid
		}
		select {
		case <-ch:
		case <-time.After(5 * time.Second):
			t.Fatal("no pid output")
		}
	}
}

// gone reports whether pid exits within 5 s. A zombie counts as gone: the
// test's PID 1 may not reap a re-parented child.
func gone(pid int) bool {
	for range 250 {
		if syscall.Kill(pid, 0) != nil || zombie(pid) {
			return true
		}
		time.Sleep(20 * time.Millisecond)
	}
	return false
}

func newCgroupManager(t *testing.T, cg *Cgroups) *Manager {
	t.Helper()
	m, err := NewManager(Config{Isolator: cg})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	return m
}

func TestCgroupCancelKillsDetachedChild(t *testing.T) {
	m := newCgroupManager(t, newTestCgroups(t))
	e, pid := startDetached(t, m, 0)
	res, already, err := m.Cancel(context.Background(), e.ID)
	if err != nil || already || res.Completion != Canceled {
		t.Fatalf("cancel: %+v %v %v", res, already, err)
	}
	if !gone(pid) {
		t.Fatalf("detached child %d survived the cgroup kill", pid)
	}
	if _, err := os.Stat(m.cfg.Isolator.(*Cgroups).Root + "/" + e.ID); !os.IsNotExist(err) {
		t.Fatalf("execution cgroup not removed: %v", err)
	}
}

func TestCgroupDeadlineKillsDetachedChild(t *testing.T) {
	m := newCgroupManager(t, newTestCgroups(t))
	e, pid := startDetached(t, m, 500*time.Millisecond)
	<-e.Done()
	if r, _ := e.Ended(); r.Completion != DeadlineExceeded {
		t.Fatalf("result %+v", r)
	}
	if !gone(pid) {
		t.Fatalf("detached child %d survived the deadline", pid)
	}
}

// Without cgroups, a child that calls setsid escapes the kill. This is why
// the daemon uses cgroups in the VM.
func TestProcessGroupMissesDetachedChild(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("runs with the cgroup tests")
	}
	m, err := NewManager(Config{Isolator: ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	e, pid := startDetached(t, m, 0)
	t.Cleanup(func() { _ = syscall.Kill(pid, syscall.SIGKILL) })
	if _, _, err := m.Cancel(context.Background(), e.ID); err != nil {
		t.Fatal(err)
	}
	if syscall.Kill(pid, 0) != nil {
		t.Fatalf("expected the detached child %d to survive a process-group kill", pid)
	}
}

func zombie(pid int) bool {
	raw, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat")
	if err != nil {
		return false
	}
	// pid (comm) state ...; comm can hold spaces, so cut at the last ')'.
	s := string(raw)
	i := strings.LastIndexByte(s, ')')
	return i >= 0 && i+2 < len(s) && s[i+2] == 'Z'
}

// A root command can make child cgroups in its execution cgroup. Cancel must
// kill their processes and remove the whole tree.
func TestCgroupCancelRemovesChildCgroups(t *testing.T) {
	cg := newTestCgroups(t)
	m := newCgroupManager(t, cg)
	script := `d=$(sed 's|^0::||' /proc/self/cgroup); mkdir /sys/fs/cgroup$d/child /sys/fs/cgroup$d/child/deeper
sleep 100 & echo $! >/sys/fs/cgroup$d/child/deeper/cgroup.procs; echo $!; sleep 100`
	e, pid := startPID(t, m, script, 0)
	dir := filepath.Join(cg.Root, e.ID)
	if _, err := os.Stat(filepath.Join(dir, "child", "deeper")); err != nil {
		t.Fatalf("child cgroup not made: %v", err)
	}
	start := time.Now()
	if res, _, err := m.Cancel(context.Background(), e.ID); err != nil || res.Completion != Canceled {
		t.Fatalf("cancel: %+v %v", res, err)
	}
	if !gone(pid) {
		t.Fatalf("process %d in the child cgroup survived", pid)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatalf("execution cgroup tree not removed: %v", err)
	}
	if d := time.Since(start); d > 3*time.Second {
		t.Fatalf("cancel took %s; Close spun on EBUSY", d)
	}
}

// A new daemon kills and removes leftover execution cgroups, child cgroups too.
func TestNewCgroupsRemovesNestedLeftovers(t *testing.T) {
	cg := newTestCgroups(t)
	left := filepath.Join(cg.Root, "leftover", "child")
	if err := os.MkdirAll(left, 0o755); err != nil {
		t.Fatal(err)
	}
	c := exec.Command("sleep", "100")
	if err := c.Start(); err != nil {
		t.Fatal(err)
	}
	waited := make(chan struct{})
	go func() { _ = c.Wait(); close(waited) }()
	t.Cleanup(func() { _ = c.Process.Kill(); <-waited })
	if err := os.WriteFile(filepath.Join(left, "cgroup.procs"), []byte(strconv.Itoa(c.Process.Pid)), 0); err != nil {
		t.Fatal(err)
	}
	if _, err := NewCgroups(cg.Root); err != nil {
		t.Fatal(err)
	}
	select {
	case <-waited:
	case <-time.After(5 * time.Second):
		t.Fatal("leftover process survived")
	}
	if _, err := os.Stat(filepath.Join(cg.Root, "leftover")); !os.IsNotExist(err) {
		t.Fatalf("leftover cgroup not removed: %v", err)
	}
}
