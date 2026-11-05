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
	"testing"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
)

// fakeProcEntry writes /proc/<pid>/ files of a Firecracker in our layout.
// unreadable makes comm a directory, so reading it fails with EISDIR.
func fakeProcEntry(t *testing.T, l *Launcher, pid int, id string, uid uint32, unreadable bool) {
	t.Helper()
	dir := filepath.Join(l.ProcFS, strconv.Itoa(pid))
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	files := map[string]string{
		"cgroup":  "0::/" + l.Cmd.Slice + "/" + jailer.ScopeUnit(id) + "\n",
		"cmdline": "/firecracker\x00--id\x00" + id + "\x00",
		"status":  fmt.Sprintf("Name:\tfirecracker\nUid:\t%d\t%d\t%d\t%d\n", uid, uid, uid, uid),
	}
	if unreadable {
		if err := os.Mkdir(filepath.Join(dir, "comm"), 0o755); err != nil {
			t.Fatal(err)
		}
	} else {
		files["comm"] = "firecracker\n"
	}
	for name, body := range files {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

func TestScanFailsOnAnUnreadableProcess(t *testing.T) {
	l := &Launcher{ProcFS: t.TempDir(), Cmd: jailer.Command{Slice: "fcvms.slice", Layout: jailer.Layout{ChrootBase: t.TempDir()}}}
	fakeProcEntry(t, l, 4242, testID, 1000007, false)
	// A process that exited during the scan: its directory is empty.
	if err := os.Mkdir(filepath.Join(l.ProcFS, "4343"), 0o755); err != nil {
		t.Fatal(err)
	}
	cands, err := l.Scan()
	if err != nil || len(cands) != 1 || cands[0] != (agent.Candidate{ID: testID, PID: 4242, UID: 1000007}) {
		t.Fatalf("scan: %+v %v", cands, err)
	}
	fakeProcEntry(t, l, 4444, "other", 1000008, true)
	if cands, err := l.Scan(); err == nil {
		t.Fatalf("scan with an unreadable process worked: %+v", cands)
	}
}

func TestRemoveKillsOnlyAfterACheckThatWorked(t *testing.T) {
	h := newFakeHost(t, "unused")
	h.l.ProcFS = t.TempDir()
	vm := exec.Command("sleep", "300")
	if err := vm.Start(); err != nil {
		t.Fatal(err)
	}
	exited := make(chan struct{})
	go func() {
		_ = vm.Wait()
		close(exited)
	}()
	defer func() {
		_ = vm.Process.Kill()
		<-exited
	}()
	alive := func() bool {
		select {
		case <-exited:
			return false
		default:
			return true
		}
	}
	pid := vm.Process.Pid
	chroot := h.l.Cmd.Layout.RootDir(testID)
	if err := os.MkdirAll(chroot, 0o755); err != nil {
		t.Fatal(err)
	}
	c := agent.Candidate{ID: testID, PID: pid}
	ctx := context.Background()

	fakeProcEntry(t, h.l, pid, testID, 1000001, true)
	if err := h.l.Remove(ctx, c); err == nil || !alive() {
		t.Fatalf("remove after a failed check: err %v, alive %v", err, alive())
	}
	if len(h.systemctlCalls(t)) != 0 {
		t.Fatalf("scope stopped after a failed check: %v", h.systemctlCalls(t))
	}

	// The process is gone from /proc: only the scope and files go.
	if err := os.RemoveAll(filepath.Join(h.l.ProcFS, strconv.Itoa(pid))); err != nil {
		t.Fatal(err)
	}
	if err := h.l.Remove(ctx, c); err != nil || !alive() {
		t.Fatalf("remove of a gone process: err %v, alive %v", err, alive())
	}
	if _, err := os.Stat(chroot); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("chroot not removed: %v", err)
	}

	fakeProcEntry(t, h.l, pid, testID, 1000001, false)
	if err := h.l.Remove(ctx, c); err != nil {
		t.Fatal(err)
	}
	<-exited
}

// TestScanInPrivateCgroupNamespace: in a pod's cgroup namespace a VM reads
// "0::/../../<slice>/fcvm-<id>.scope". Scan finds it when the host tree
// lists its PID, and skips a process the host scope does not list.
func TestScanInPrivateCgroupNamespace(t *testing.T) {
	host := t.TempDir()
	l := &Launcher{ProcFS: t.TempDir(), Cmd: jailer.Command{Slice: "fcvms.slice", Layout: jailer.Layout{ChrootBase: t.TempDir()}},
		Cgroups: CgroupView{Private: true, HostCgroupFS: host}}
	fakeProcEntry(t, l, 4242, testID, 1000007, false)
	podView := "0::/../../" + l.Cmd.Slice + "/" + jailer.ScopeUnit(testID) + "\n"
	if err := os.WriteFile(filepath.Join(l.ProcFS, "4242", "cgroup"), []byte(podView), 0o644); err != nil {
		t.Fatal(err)
	}
	stat := "4242 (firecracker) S" + strings.Repeat(" 0", 18) + " 777\n"
	if err := os.WriteFile(filepath.Join(l.ProcFS, "4242", "stat"), []byte(stat), 0o644); err != nil {
		t.Fatal(err)
	}
	// The host form, as seen from a private namespace, is a cgroup inside the pod.
	fakeProcEntry(t, l, 4343, "22222222-2222-4222-8222-222222222222", 1000008, false)
	// The same VM ID and pod view, but the host scope does not list the PID:
	// Scan reaches the cgroup.procs check and skips it.
	fakeProcEntry(t, l, 4444, testID, 1000009, false)
	if err := os.WriteFile(filepath.Join(l.ProcFS, "4444", "cgroup"), []byte(podView), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(l.ProcFS, "4444", "stat"), []byte(strings.Replace(stat, "4242", "4444", 1)), 0o644); err != nil {
		t.Fatal(err)
	}
	scope := filepath.Join(host, l.Cmd.Slice, jailer.ScopeUnit(testID))
	if err := os.MkdirAll(scope, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(scope, "cgroup.procs"), []byte("4242\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	cands, err := l.Scan()
	if err != nil || len(cands) != 1 || cands[0] != (agent.Candidate{ID: testID, PID: 4242, UID: 1000007}) {
		t.Fatalf("scan: %+v %v", cands, err)
	}
	if err := l.verify(testID, 4242, 0); err != nil {
		t.Fatalf("verify: %v", err)
	}
	if err := l.verify(testID, 4444, 0); !errors.Is(err, agent.ErrGone) {
		t.Fatalf("verify of a PID the host scope does not list: %v", err)
	}
	// Without the host scope the VM counts as gone, never as a match.
	if err := os.WriteFile(filepath.Join(scope, "cgroup.procs"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := l.verify(testID, 4242, 0); !errors.Is(err, agent.ErrGone) {
		t.Fatalf("verify without host listing: %v", err)
	}
}
