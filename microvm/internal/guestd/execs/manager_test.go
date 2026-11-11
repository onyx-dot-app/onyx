package execs

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestNewManagerValidates(t *testing.T) {
	for name, cfg := range map[string]Config{
		"nil isolator":      {},
		"negative output":   {Isolator: ProcessGroups{}, OutputBytes: -1},
		"negative running":  {Isolator: ProcessGroups{}, MaxRunning: -1},
		"negative tracked":  {Isolator: ProcessGroups{}, MaxTracked: -1},
		"negative budget":   {Isolator: ProcessGroups{}, OutputBudget: -1},
		"negative ttl":      {Isolator: ProcessGroups{}, EndedTTL: -time.Second},
		"negative deadline": {Isolator: ProcessGroups{}, DefaultDeadline: -time.Second},
		"default above max": {Isolator: ProcessGroups{}, DefaultDeadline: 2 * time.Hour, MaxDeadline: time.Hour},
	} {
		if _, err := NewManager(cfg); err == nil {
			t.Errorf("%s: no error", name)
		}
	}
}

// Ended records expire on the timer, also when no new command starts.
func TestEndedRecordsExpireWhenIdle(t *testing.T) {
	m, err := NewManager(Config{Isolator: ProcessGroups{}, EndedTTL: 500 * time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	e, err := m.Start(Spec{Argv: []string{"true"}, Env: []string{"PATH=/usr/bin:/bin"}})
	if err != nil {
		t.Fatal(err)
	}
	<-e.Done()
	if got := m.List(nil); len(got) != 1 || got[0].ID != e.ID {
		t.Fatalf("ended record not kept before it expired: %v", got)
	}
	deadline := time.Now().Add(5 * time.Second)
	for len(m.List(nil)) > 0 {
		if time.Now().After(deadline) {
			t.Fatal("ended record did not expire")
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestLookPathRelativeToCommandDir(t *testing.T) {
	dir := t.TempDir()
	bin := filepath.Join(dir, "node_modules", ".bin")
	if err := os.MkdirAll(bin, 0o755); err != nil {
		t.Fatal(err)
	}
	tool := filepath.Join(bin, "tool")
	if err := os.WriteFile(tool, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	got, err := lookPath("tool", dir, []string{"PATH=node_modules/.bin:/usr/bin"})
	if err != nil || got != tool {
		t.Fatalf("lookPath: %q %v", got, err)
	}
	if _, err := lookPath("tool", t.TempDir(), []string{"PATH=node_modules/.bin"}); err == nil {
		t.Fatal("found tool in another dir")
	}
}

// A Cancel that lands after the main process exited keeps its exit code.
func TestCancelAfterExitKeepsExitCode(t *testing.T) {
	m, err := NewManager(Config{Isolator: ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	canceled := make(chan error, 1)
	afterExit = func(e *Execution) {
		go func() {
			_, _, err := m.Cancel(context.Background(), e.ID)
			canceled <- err
		}()
		// Let the Cancel reach kill before the result is recorded.
		time.Sleep(50 * time.Millisecond)
	}
	t.Cleanup(func() { afterExit = nil })
	e, err := m.Start(Spec{Argv: []string{"sh", "-c", "exit 3"}, Env: []string{"PATH=/usr/bin:/bin"}})
	if err != nil {
		t.Fatal(err)
	}
	<-e.Done()
	if err := <-canceled; err != nil {
		t.Fatal(err)
	}
	if res, _ := e.Ended(); res.Completion != Exited || res.ExitCode != 3 {
		t.Fatalf("completion %s exit %d signal %d", res.Completion, res.ExitCode, res.Signal)
	}
}

func TestOutputBudget(t *testing.T) {
	m, err := NewManager(Config{Isolator: ProcessGroups{}, OutputBytes: 64 << 10, OutputBudget: 256 << 10})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	env := []string{"PATH=/usr/bin:/bin"}
	// 64 KiB of stdout each.
	burst := []string{"sh", "-c", "head -c 65536 /dev/zero"}
	var ended []*Execution
	for range 3 {
		e, err := m.Start(Spec{Argv: burst, Env: env})
		if err != nil {
			t.Fatal(err)
		}
		<-e.Done()
		ended = append(ended, e)
	}
	if got := m.used.Load(); got < 3*(64<<10) || got > 256<<10 {
		t.Fatalf("used %d after three ended records", got)
	}
	// A running command that keeps writing pushes the total over the budget.
	stdin := Spec{Argv: []string{"sh", "-c", "head -c 65536 /dev/zero; head -c 65536 /dev/zero >&2; cat >/dev/null"}, Env: env, Stdin: true}
	run, err := m.Start(stdin)
	if err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for run.Info().Bytes != [2]int64{64 << 10, 64 << 10} {
		if time.Now().After(deadline) {
			t.Fatalf("running output %v", run.Info().Bytes)
		}
		time.Sleep(5 * time.Millisecond)
	}
	if got := m.used.Load(); got > 256<<10 {
		t.Fatalf("used %d is over the budget", got)
	}
	// The oldest ended record lost its output first; the newest kept it.
	if data, gapTo, _ := ended[0].Read(Stdout, 0, 1<<20); len(data) != 0 || gapTo != 64<<10 {
		t.Fatalf("oldest ended record kept %d bytes (gap to %d)", len(data), gapTo)
	}
	if data, _, _ := ended[2].Read(Stdout, 0, 1<<20); len(data) != 64<<10 {
		t.Fatalf("newest ended record kept %d bytes", len(data))
	}
	if data, _, _ := run.Read(Stderr, 0, 1<<20); len(data) == 0 {
		t.Fatal("running record lost all its output")
	}
	if _, err := run.WriteStdin(nil, true); err != nil {
		t.Fatal(err)
	}
	<-run.Done()
}

// Over the budget with no ended record left, running records keep their
// latest bytes.
func TestOutputBudgetTrimsRunning(t *testing.T) {
	m, err := NewManager(Config{Isolator: ProcessGroups{}, OutputBytes: 1 << 20, OutputBudget: 128 << 10})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	e, err := m.Start(Spec{
		Argv: []string{"sh", "-c", "head -c 262144 /dev/zero; printf END; cat >/dev/null"},
		Env:  []string{"PATH=/usr/bin:/bin"}, Stdin: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for e.Info().Bytes[Stdout] != 262144+3 {
		if time.Now().After(deadline) {
			t.Fatalf("output %v", e.Info().Bytes)
		}
		time.Sleep(5 * time.Millisecond)
	}
	if got := m.used.Load(); got > 128<<10 {
		t.Fatalf("used %d is over the budget", got)
	}
	data, gapTo, next := e.Read(Stdout, 0, 1<<20)
	if gapTo == 0 || next != 262144+3 || !strings.HasSuffix(string(data), "END") {
		t.Fatalf("kept %d bytes, gap to %d, next %d", len(data), gapTo, next)
	}
	if _, err := e.WriteStdin(nil, true); err != nil {
		t.Fatal(err)
	}
	<-e.Done()
}

// Over MaxTracked, Start drops the least recently used ended record, never a
// running one; with every record running it fails with ErrCapReached.
func TestTrackedCapEvictsLeastRecentlyUsedEnded(t *testing.T) {
	m, err := NewManager(Config{Isolator: ProcessGroups{}, MaxTracked: 3})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	env := []string{"PATH=/usr/bin:/bin"}
	start := func(argv ...string) *Execution {
		t.Helper()
		e, err := m.Start(Spec{Argv: argv, Env: env})
		if err != nil {
			t.Fatal(err)
		}
		return e
	}
	running := start("sleep", "30")
	a, b := start("true"), start("true")
	<-a.Done()
	<-b.Done()
	// a is older, but a Get makes it the most recently used.
	time.Sleep(time.Millisecond)
	if _, err := m.Get(a.ID); err != nil {
		t.Fatal(err)
	}
	c := start("sleep", "30")
	if _, err := m.Get(b.ID); err == nil {
		t.Fatal("b (least recently used, ended) was kept")
	}
	for _, e := range []*Execution{running, a, c} {
		if _, err := m.Get(e.ID); err != nil {
			t.Fatalf("%s dropped: %v", e.Argv, err)
		}
	}
	d := start("sleep", "30") // drops a, the last ended record
	if _, err := m.Get(a.ID); err == nil {
		t.Fatal("a kept over the cap")
	}
	if _, err := m.Start(Spec{Argv: []string{"true"}, Env: env}); !errors.Is(err, ErrCapReached) {
		t.Fatalf("all running: %v", err)
	}
	for _, e := range []*Execution{running, c, d} {
		if _, err := m.Get(e.ID); err != nil {
			t.Fatalf("running record dropped: %v", err)
		}
	}
}

// Signal reaches every process of the main process's group and does not wait.
func TestSignalProcessGroup(t *testing.T) {
	m, err := NewManager(Config{Isolator: ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	// The shell handles SIGINT; its foreground child sleep does not and dies.
	e, err := m.Start(Spec{Argv: []string{"sh", "-c", `trap 'echo shell-int' INT; echo ready; sleep 30; echo "sleep-rc $?"`},
		Env: []string{"PATH=/usr/bin:/bin"}})
	if err != nil {
		t.Fatal(err)
	}
	for deadline := time.Now().Add(5 * time.Second); ; time.Sleep(10 * time.Millisecond) {
		if data, _, _ := e.Read(Stdout, 0, 64); strings.Contains(string(data), "ready") {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("no ready")
		}
	}
	waitChild(t, e.PID, "sleep")
	if _, ended, err := m.Signal(e.ID, syscall.SIGINT); err != nil || ended {
		t.Fatalf("signal: %v %v", ended, err)
	}
	select {
	case <-e.Done():
	case <-time.After(10 * time.Second):
		t.Fatal("sleep did not get SIGINT")
	}
	data, _, _ := e.Read(Stdout, 0, 1024)
	res, _ := e.Ended()
	if !strings.Contains(string(data), "shell-int") || !strings.Contains(string(data), "sleep-rc 130") || res.Completion != Exited {
		t.Fatalf("output %q result %+v", data, res)
	}
}

// A Start that does not start a command keeps every ended record.
func TestCapKeepsRecordsWhenStartFails(t *testing.T) {
	m, err := NewManager(Config{Isolator: ProcessGroups{}, MaxTracked: 2, MaxRunning: 1})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	env := []string{"PATH=/usr/bin:/bin"}
	ended, err := m.Start(Spec{Argv: []string{"true"}, Env: env})
	if err != nil {
		t.Fatal(err)
	}
	<-ended.Done()
	running, err := m.Start(Spec{Argv: []string{"sleep", "30"}, Env: env})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := m.Start(Spec{Argv: []string{"true"}, Env: env}); !errors.Is(err, ErrTooMany) {
		t.Fatalf("over MaxRunning: %v", err)
	}
	if _, err := m.Get(ended.ID); err != nil {
		t.Fatalf("ErrTooMany dropped the ended record: %v", err)
	}
	if _, _, err := m.Cancel(context.Background(), running.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := m.Start(Spec{Argv: []string{"/no/such/program"}, Env: env}); err == nil {
		t.Fatal("a missing program started")
	}
	if len(m.List(nil)) != 2 {
		t.Fatalf("a failed start dropped a record: %d left", len(m.List(nil)))
	}
}

// waitChild waits until pid has a child process named name.
func waitChild(t *testing.T, pid int, name string) {
	t.Helper()
	for deadline := time.Now().Add(10 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
		if exec.Command("pgrep", "-P", strconv.Itoa(pid), "-x", name).Run() == nil {
			return
		}
	}
	t.Fatalf("no %s child of %d", name, pid)
}

// The first soft signal decides the completion, also when a second one
// follows before the exit is read.
func TestFirstSoftSignalDecidesCompletion(t *testing.T) {
	m, err := NewManager(Config{Isolator: ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	e, err := m.Start(Spec{Argv: []string{"sleep", "30"}, Env: []string{"PATH=/usr/bin:/bin"}})
	if err != nil {
		t.Fatal(err)
	}
	for _, sig := range []syscall.Signal{syscall.SIGINT, syscall.SIGTERM} {
		if _, _, err := m.Signal(e.ID, sig); err != nil {
			t.Fatal(err)
		}
	}
	<-e.Done()
	if res, _ := e.Ended(); res.Completion != Canceled || res.Signal != int(syscall.SIGINT) {
		t.Fatalf("result %+v", res)
	}
}
