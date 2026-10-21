//go:build !windows

package devstack

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestDiagnosticLogReadsAreBounded(t *testing.T) {
	path := filepath.Join(t.TempDir(), "service.log")
	contents := strings.Repeat("old log line\n", maxLogTailBytes) + "EADDRINUSE: address already in use\nlast line\n"
	if err := os.WriteFile(path, []byte(contents), 0o600); err != nil {
		t.Fatal(err)
	}
	data, err := readLogTail(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(data) != maxLogTailBytes || !strings.HasSuffix(string(data), "last line\n") {
		t.Fatalf("bounded tail has %d bytes and incorrect suffix", len(data))
	}
	if tail := logTail(path, 2); tail != "EADDRINUSE: address already in use\nlast line" {
		t.Fatalf("unexpected diagnostic tail: %q", tail)
	}
	if !failedBind(ServiceRecord{Port: 12345, Log: path}) {
		t.Fatal("bounded tail lost bind failure marker")
	}
}

func TestWorkerStatusHonorsPersistedSettling(t *testing.T) {
	stack := newTestStack(t, t.TempDir())
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	record, err := startService(Spec{Name: "worker", Slug: "worker", Command: []string{executable}, Dir: os.TempDir(), Env: []string{fakeServiceEnv + "=1"}}, filepath.Join(stack.LogDir(), "worker.log"))
	if err != nil {
		t.Fatal(err)
	}
	state := &State{Phase: PhaseStarting, SettleTime: time.Hour, Services: []ServiceRecord{record}}
	if err := stack.WriteState(state); err != nil {
		t.Fatal(err)
	}
	status, err := stack.waitReady(context.Background(), state, time.Millisecond, state.SettleTime)
	if err == nil || status.Ready || status.Phase != PhaseDegraded || len(status.Errors) == 0 {
		t.Fatalf("short startup timeout returned inconsistent status: %+v, %v", status, err)
	}
	status, err = stack.Status()
	if err != nil || status.Ready {
		t.Fatalf("persisted settling ignored: %+v, %v", status, err)
	}
	state.Services[0].StartedAt = time.Now().Add(-2 * time.Hour)
	if err := stack.WriteState(state); err != nil {
		t.Fatal(err)
	}
	status, err = stack.Status()
	if err != nil || !status.Ready {
		t.Fatalf("settled worker not ready: %+v, %v", status, err)
	}
	state.SettleTime = 0
	state.Services[0].StartedAt = time.Now()
	if status := stack.status(state, true); status.Ready {
		t.Fatal("legacy state bypassed default five-second settling")
	}
}

func TestExitedWorkerReturnsUpdatedFailureStatus(t *testing.T) {
	stack := newTestStack(t, t.TempDir())
	state := &State{Phase: PhaseStarting, Services: []ServiceRecord{{Name: "worker", Slug: "worker"}}}
	status, err := stack.waitReady(context.Background(), state, time.Second, time.Second)
	if err == nil || status.Ready || status.Phase != PhaseFailed || len(status.Errors) == 0 {
		t.Fatalf("exited worker returned stale status: %+v, %v", status, err)
	}
}
