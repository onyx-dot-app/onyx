//go:build unix

package sysops

import (
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"syscall"
	"testing"
	"time"
)

func TestSignalPIDFile(t *testing.T) {
	dir := t.TempDir()
	if ok, err := SignalPIDFile(filepath.Join(dir, "none.pid")); ok || err != nil {
		t.Fatalf("missing file: %v %v", ok, err)
	}
	ch := make(chan os.Signal, 1)
	signal.Notify(ch, syscall.SIGHUP)
	defer signal.Stop(ch)
	pf := filepath.Join(dir, "self.pid")
	if err := os.WriteFile(pf, []byte(strconv.Itoa(os.Getpid())+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if ok, err := SignalPIDFile(pf); !ok || err != nil {
		t.Fatalf("signal self: %v %v", ok, err)
	}
	select {
	case <-ch:
	case <-time.After(5 * time.Second):
		t.Fatal("no SIGHUP")
	}
	// A process that has exited.
	c := exec.Command("true")
	if err := c.Run(); err != nil {
		t.Fatal(err)
	}
	_ = os.WriteFile(pf, []byte(strconv.Itoa(c.Process.Pid)), 0o600)
	if ok, err := SignalPIDFile(pf); ok || err != nil {
		t.Fatalf("gone process: %v %v", ok, err)
	}
}

func TestRunAttach(t *testing.T) {
	dir := t.TempDir()
	ok := filepath.Join(dir, "ok")
	bad := filepath.Join(dir, "bad")
	for name, body := range map[string]string{ok: "#!/bin/sh\nexit 0\n", bad: "#!/bin/sh\necho no scratch drive >&2\nexit 1\n"} {
		if err := os.WriteFile(name, []byte(body), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := RunAttach(ok, 5*time.Second); err != nil {
		t.Fatal(err)
	}
	if err := RunAttach(bad, 5*time.Second); err == nil {
		t.Fatal("failing attach returned no error")
	}
	if err := RunAttach(filepath.Join(dir, "missing"), 5*time.Second); err == nil {
		t.Fatal("missing attach returned no error")
	}
}

// A child that keeps the output pipe open must not hold RunAttach past its
// timeout.
func TestRunAttachTimeoutWithStuckChild(t *testing.T) {
	old := attachWaitDelay
	attachWaitDelay = 200 * time.Millisecond
	t.Cleanup(func() { attachWaitDelay = old })
	script := filepath.Join(t.TempDir(), "stuck")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nsleep 1 &\nsleep 1\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	start := time.Now()
	if err := RunAttach(script, 300*time.Millisecond); err == nil {
		t.Fatal("timed-out attach returned no error")
	}
	if d := time.Since(start); d > 5*time.Second {
		t.Fatalf("RunAttach returned after %s", d)
	}
}
