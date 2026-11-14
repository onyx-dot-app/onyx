//go:build linux

package fcvm

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/unix"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
)

const testID = "11111111-1111-4111-8111-111111111111"

// fakeHost puts fake systemd-run, systemctl and jailer scripts first in PATH.
// The jailer starts a sleep (the "VM") and writes pidFile as its PID file.
// systemctl logs its calls, kills the sleep on "kill", and fails while the
// file "fail" exists.
type fakeHost struct {
	dir string
	l   *Launcher
}

func newFakeHost(t *testing.T, pidFile string) *fakeHost {
	t.Helper()
	if os.Geteuid() != 0 {
		t.Skip("needs root (chown to the VM UID)")
	}
	dir := t.TempDir()
	scripts := map[string]string{
		"systemd-run": "#!/bin/sh\nwhile [ \"$1\" != -- ]; do shift; done\nshift\nexec \"$@\"\n",
		"systemctl": fmt.Sprintf("#!/bin/sh\necho \"$*\" >> %[1]s/systemctl.log\n"+
			"if [ -e %[1]s/fail ]; then echo boom; exit 1; fi\n"+
			"if [ \"$1\" = kill ] && [ -e %[1]s/vm.pid ]; then kill -9 \"$(cat %[1]s/vm.pid)\"; fi\n", dir),
		"jailer": fmt.Sprintf("#!/bin/sh\nwhile [ \"$1\" != -- ]; do\n"+
			"  case \"$1\" in --id) id=$2;; --chroot-base-dir) base=$2;; esac; shift\ndone\n"+
			"readlink /proc/self/ns/net > %[1]s/netns\n"+
			"sleep 300 </dev/null >/dev/null 2>&1 &\necho $! > %[1]s/vm.pid\n"+
			"echo %[2]s > \"$base/firecracker/$id/root/firecracker.pid\"\n", dir, pidFile),
	}
	for name, body := range scripts {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", dir+":"+os.Getenv("PATH"))
	l := &Launcher{
		Cmd: jailer.Command{
			JailerBin: filepath.Join(dir, "jailer"), FirecrackerBin: "/bin/false",
			Layout: jailer.Layout{ChrootBase: filepath.Join(dir, "jail")}, Slice: "test.slice",
		},
		Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	return &fakeHost{dir: dir, l: l}
}

func (h *fakeHost) systemctlCalls(t *testing.T) []string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(h.dir, "systemctl.log"))
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		t.Fatal(err)
	}
	return strings.Fields(strings.ReplaceAll(strings.TrimSpace(string(raw)), " ", "_"))
}

// vmAlive reports whether the fake VM still runs (a zombie counts as gone).
func (h *fakeHost) vmAlive(t *testing.T) bool {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(h.dir, "vm.pid"))
	if err != nil {
		t.Fatal(err)
	}
	stat, err := os.ReadFile("/proc/" + strings.TrimSpace(string(raw)) + "/stat")
	if err != nil {
		return false
	}
	s := string(stat)
	return !strings.HasPrefix(strings.Fields(s[strings.LastIndexByte(s, ')')+1:])[0], "Z")
}

func TestSpawnStopsTheScopeWhenItFailsBeforeAProc(t *testing.T) {
	h := newFakeHost(t, "not-a-pid")
	_, err := h.l.Spawn(context.Background(), testID, 1000000, nil, jailer.Limits{})
	if err == nil || errors.Is(err, agent.ErrVMLeft) {
		t.Fatalf("spawn: %v", err)
	}
	unit := jailer.ScopeUnit(testID)
	if got, want := h.systemctlCalls(t), []string{"kill_--signal=SIGKILL_" + unit, "stop_" + unit}; strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("systemctl calls %v, want %v", got, want)
	}
	if h.vmAlive(t) {
		t.Fatal("the VM still runs")
	}
	if _, err := os.Stat(h.l.Cmd.Layout.ChrootDir(testID)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("chroot not removed: %v", err)
	}
}

func TestSpawnStartsTheJailerInANewNetworkNamespace(t *testing.T) {
	h := newFakeHost(t, "not-a-pid")
	_, _ = h.l.Spawn(context.Background(), testID, 1000000, nil, jailer.Limits{})
	raw, err := os.ReadFile(filepath.Join(h.dir, "netns"))
	if err != nil {
		t.Fatal(err)
	}
	own, err := os.Readlink("/proc/self/ns/net")
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.TrimSpace(string(raw)); got == "" || got == own {
		t.Fatalf("jailer network namespace %q, want a new one (agent %q)", got, own)
	}
}

func TestSpawnKeepsTheChrootWhenTheVMMayStillRun(t *testing.T) {
	h := newFakeHost(t, "not-a-pid")
	if err := os.WriteFile(filepath.Join(h.dir, "fail"), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	_, err := h.l.Spawn(context.Background(), testID, 1000000, nil, jailer.Limits{})
	if !errors.Is(err, agent.ErrVMLeft) {
		t.Fatalf("spawn error %v does not wrap ErrVMLeft", err)
	}
	if _, err := os.Stat(h.l.Cmd.Layout.ChrootDir(testID)); err != nil {
		t.Fatalf("chroot removed: %v", err)
	}
	_ = os.Remove(filepath.Join(h.dir, "fail"))
	if err := h.l.killScope(context.Background(), testID); err != nil {
		t.Fatal(err)
	}
}

func TestKillCanBeRetried(t *testing.T) {
	h := newFakeHost(t, "unused")
	vm := exec.Command("sleep", "300")
	if err := vm.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() {
		_ = vm.Process.Kill()
		_ = vm.Wait()
	}()
	pidfd, err := unix.PidfdOpen(vm.Process.Pid, 0)
	if err != nil {
		t.Fatal(err)
	}
	chroot := h.l.Cmd.Layout.RootDir(testID)
	if err := os.MkdirAll(chroot, 0o755); err != nil {
		t.Fatal(err)
	}
	// No watcher yet: the first Kill times out waiting for the exit.
	p := &Proc{ID: testID, pid: vm.Process.Pid, pidfd: pidfd, done: make(chan struct{}), l: h.l}
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if err := p.Kill(ctx); err == nil {
		t.Fatal("first Kill succeeded without an exit")
	}
	go p.watch()
	for i := range 2 {
		if err := p.Kill(context.Background()); err != nil {
			t.Fatalf("kill %d: %v", i+2, err)
		}
	}
	if _, err := os.Stat(h.l.Cmd.Layout.ChrootDir(testID)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("chroot not removed: %v", err)
	}
	if got := h.systemctlCalls(t); len(got) != 1 {
		t.Fatalf("systemctl calls %v, want one scope stop", got)
	}
}
