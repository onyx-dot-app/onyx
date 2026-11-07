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
