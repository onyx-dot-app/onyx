//go:build !windows

package devstack

import (
	"context"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"syscall"
	"testing"
	"time"
)

func TestSpecHashIgnoresAgentSession(t *testing.T) {
	a := Spec{Name: "api", Env: []string{"TMUX_PANE=%1", "TERM_SESSION_ID=agent-a", "CODEX_SESSION_ID=a", "GEN_AI_API_KEY=original"}}
	b := a
	b.Env = []string{"TMUX_PANE=%2", "TERM_SESSION_ID=agent-b", "CODEX_SESSION_ID=b", "GEN_AI_API_KEY=original"}
	if a.Hash() != b.Hash() {
		t.Fatal("agent session metadata changed service identity")
	}
	b.Env = []string{"GEN_AI_API_KEY=changed"}
	if a.Hash() == b.Hash() {
		t.Fatal("changed application credentials did not change service identity")
	}
}

func TestUpRetriesActualChildBindFailure(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	marker := filepath.Join(t.TempDir(), "race")
	p := &fakeProvider{services: []string{"web"}, extraArgs: map[string][]string{"web": {"--race-once", marker}}}
	listeners := make(chan net.Listener, 1)
	errors := make(chan error, 1)
	go func() {
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) {
			data, err := os.ReadFile(marker)
			port, parseErr := strconv.Atoi(string(data))
			if err == nil && parseErr == nil {
				listener, err := net.Listen("tcp", fmt.Sprintf(":%d", port))
				if err != nil {
					errors <- err
					return
				}
				listeners <- listener
				errors <- os.WriteFile(marker+".ready", nil, 0o600)
				return
			}
			time.Sleep(10 * time.Millisecond)
		}
		errors <- fmt.Errorf("service never reached bind barrier")
	}()
	t.Cleanup(func() {
		select {
		case listener := <-listeners:
			_ = listener.Close()
		default:
		}
	})
	status := mustUp(t, s, p)
	if err := <-errors; err != nil {
		t.Fatal(err)
	}
	listener := <-listeners
	defer func() { _ = listener.Close() }()
	foreignPort := listener.Addr().(*net.TCPAddr).Port
	if status.Ports["web"] == foreignPort {
		t.Fatal("stack did not move off the port claimed during launch")
	}
	if bindable(foreignPort) {
		t.Fatal("stack interfered with the competing listener")
	}
}

func TestStopRetainsUnverifiedSurvivingGroup(t *testing.T) {
	s := newTestStack(t, t.TempDir())
	p := &fakeProvider{services: []string{"web"}, extraArgs: map[string][]string{"web": {"--spawn-child"}}}
	mustUp(t, s, p)
	rec := servicePID(t, s, "web")
	t.Cleanup(func() {
		_ = syscall.Kill(-rec.PGID, syscall.SIGKILL)
		deadline := time.Now().Add(3 * time.Second)
		for groupAlive(rec.PGID) && time.Now().Before(deadline) {
			time.Sleep(10 * time.Millisecond)
		}
	})
	deadline := time.Now().Add(5 * time.Second)
	for len(groupMembers(rec.PGID)) < 2 {
		if time.Now().After(deadline) {
			t.Fatal("child did not start")
		}
		time.Sleep(10 * time.Millisecond)
	}
	if err := syscall.Kill(rec.PID, syscall.SIGKILL); err != nil {
		t.Fatal(err)
	}
	for pidAlive(rec.PID) && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	rec.Members = nil
	if err := s.WriteState(&State{Phase: PhaseReady, Services: []ServiceRecord{rec}}); err != nil {
		t.Fatal(err)
	}
	if err := s.Stop(context.Background(), testOptions()); err == nil {
		t.Fatal("unverified surviving group was silently discarded")
	}
	state, err := s.ReadState()
	if err != nil || state == nil || len(state.Services) != 1 || state.Phase != PhaseFailed {
		t.Fatalf("ownership failure was not retained: %+v, %v", state, err)
	}
	if !groupAlive(rec.PGID) {
		t.Fatal("unverified group was killed")
	}
}
