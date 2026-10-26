//go:build !windows

package devstack

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

func TestRunServiceTerminalInterruptStopsStubbornChild(t *testing.T) {
	script, err := exec.LookPath("script")
	if err != nil {
		t.Skip("script is required to allocate a disposable terminal")
	}
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	var args []string
	switch runtime.GOOS {
	case "darwin":
		args = []string{"-q", "/dev/null", executable, "-test.run=^TestRunServiceTerminalInterruptHelper$"}
	case "linux":
		quoted := "'" + strings.ReplaceAll(executable, "'", "'\"'\"'") + "'"
		args = []string{"-q", "-c", quoted + " -test.run=^TestRunServiceTerminalInterruptHelper$", "/dev/null"}
	default:
		t.Skip("terminal fixture supports macOS and Linux")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, script, args...)
	cmd.Env = append(os.Environ(), "ODS_TEST_TERMINAL_INTERRUPT=1")
	input, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = input.Close() }()
	defer func() { _ = writer.Close() }()
	output, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	cmd.Stdin, cmd.Stderr = input, cmd.Stdout
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	var transcript strings.Builder
	scanner := bufio.NewScanner(output)
	sent := false
	for scanner.Scan() {
		line := scanner.Text()
		transcript.WriteString(line + "\n")
		if line == "interrupt ready\r" || line == "interrupt ready" {
			if _, err := writer.Write([]byte{3}); err != nil {
				t.Error(err)
			}
			sent = true
		}
	}
	readErr := scanner.Err()
	err = cmd.Wait()
	if err != nil || readErr != nil || !sent || !strings.Contains(transcript.String(), "interrupt stopped; terminal restored") {
		t.Fatalf("terminal interrupt: exit=%v read=%v sent=%v\n%s", err, readErr, sent, transcript.String())
	}
}

func TestRunServiceTerminalInterruptHelper(t *testing.T) {
	if os.Getenv("ODS_TEST_TERMINAL_INTERRUPT") != "1" {
		return
	}
	foreground, err := unix.IoctlGetInt(int(os.Stdin.Fd()), unix.TIOCGPGRP)
	if err != nil {
		t.Fatal(err)
	}
	s, target, launch := runnerShellFixture(t, `trap '' INT TERM; printf 'interrupt ready\n'; while :; do sleep 1; done`)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	err = s.RunService(ctx, target, launch, "model", ServiceOptions{
		PreferredPort: testBasePort + 200, StopTimeout: 100 * time.Millisecond,
		IO: ServiceIO{Stdin: os.Stdin, Stdout: os.Stdout, Stderr: os.Stderr},
	})
	if ctx.Err() != nil {
		t.Fatalf("terminal Ctrl-C did not start bounded shutdown before watchdog: %v", err)
	}
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		t.Fatalf("stubborn child exit=%v, want forced termination", err)
	}
	status, ok := exitErr.Sys().(syscall.WaitStatus)
	if !ok || !status.Signaled() || status.Signal() != syscall.SIGKILL {
		t.Fatalf("stubborn child status=%v, want SIGKILL", exitErr.Sys())
	}
	current, err := unix.IoctlGetInt(int(os.Stdin.Fd()), unix.TIOCGPGRP)
	if err != nil || current != foreground {
		t.Fatalf("terminal foreground group=%d, want %d: %v", current, foreground, err)
	}
	state, err := s.ReadState()
	if err != nil {
		t.Fatal(err)
	}
	if state == nil {
		t.Fatal("service state missing after terminal interrupt")
	}
	for _, service := range state.Services {
		if isCurrent(service) || groupAlive(service.PGID) {
			t.Fatalf("service survived terminal interrupt: %+v", service)
		}
	}
	fmt.Println("interrupt stopped; terminal restored")
}

func TestServiceReadsForegroundTerminalInput(t *testing.T) {
	script, err := exec.LookPath("script")
	if err != nil {
		t.Skip("script is required to allocate a disposable terminal")
	}
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	var args []string
	switch runtime.GOOS {
	case "darwin":
		args = []string{"-q", "/dev/null", executable, "-test.run=^TestServiceTerminalHelper$"}
	case "linux":
		quoted := "'" + strings.ReplaceAll(executable, "'", "'\"'\"'") + "'"
		args = []string{"-q", "-c", quoted + " -test.run=^TestServiceTerminalHelper$", "/dev/null"}
	default:
		t.Skip("terminal fixture supports macOS and Linux")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, script, args...)
	cmd.Env = append(os.Environ(), "ODS_TEST_TERMINAL_HELPER=1")
	input, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = input.Close() }()
	defer func() { _ = writer.Close() }()
	if _, err := writer.WriteString("terminal input\n"); err != nil {
		t.Fatal(err)
	}
	cmd.Stdin = input
	output, err := cmd.CombinedOutput()
	if err != nil || !strings.Contains(string(output), "service:terminal input") || !strings.Contains(string(output), "terminal restored") {
		t.Fatalf("terminal service: %v\n%s", err, output)
	}
}

func TestServiceTerminalHelper(t *testing.T) {
	if os.Getenv("ODS_TEST_TERMINAL_HELPER") != "1" {
		return
	}
	foreground, err := unix.IoctlGetInt(int(os.Stdin.Fd()), unix.TIOCGPGRP)
	if err != nil {
		t.Fatal(err)
	}
	sp := Spec{Name: "terminal reader", Slug: "web", Dir: t.TempDir(), Env: os.Environ(), Command: []string{"/bin/sh", "-c", "read value; printf 'service:%s\\n' \"$value\""}}
	record, done, err := launchService(sp, filepath.Join(t.TempDir(), "service.log"), ServiceIO{Stdin: os.Stdin, Stdout: os.Stdout, Stderr: os.Stderr})
	if err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		state, _ := exec.Command("ps", "-p", fmt.Sprint(record.PID), "-o", "stat=").Output()
		_ = syscall.Kill(-record.PGID, syscall.SIGKILL)
		<-done
		t.Fatalf("terminal reader stopped or hung: process state %q", strings.TrimSpace(string(state)))
	}
	current, err := unix.IoctlGetInt(int(os.Stdin.Fd()), unix.TIOCGPGRP)
	if err != nil || current != foreground {
		t.Fatalf("terminal foreground group=%d, want %d: %v", current, foreground, err)
	}
	sp.Command = []string{"/bin/sh", "-c", "exit 0"}
	_, done, err = launchService(sp, filepath.Join(t.TempDir(), "idle-input.log"), ServiceIO{Stdin: os.Stdin})
	if err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("service exit waited for idle terminal input")
	}
	sp.Command = []string{filepath.Join(t.TempDir(), "missing-service")}
	if _, _, err := launchService(sp, filepath.Join(t.TempDir(), "failed.log"), ServiceIO{Stdin: os.Stdin}); err == nil {
		t.Fatal("missing service started")
	}
	current, err = unix.IoctlGetInt(int(os.Stdin.Fd()), unix.TIOCGPGRP)
	if err != nil || current != foreground {
		t.Fatalf("terminal group after failed start=%d, want %d: %v", current, foreground, err)
	}
	fmt.Println("terminal restored")
}

func TestServiceZeroGraceWaitsForForcedTermination(t *testing.T) {
	ready := filepath.Join(t.TempDir(), "ready")
	sp := Spec{Name: "stubborn", Slug: "model", Dir: t.TempDir(), Env: os.Environ(), Command: []string{"/bin/sh", "-c", `trap '' INT TERM; printf ready > "$1"; while :; do sleep 1; done`, "fixture", ready}}
	record, done, err := launchService(sp, filepath.Join(t.TempDir(), "service.log"), ServiceIO{})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = syscall.Kill(-record.PGID, syscall.SIGKILL) })
	deadline := time.Now().Add(time.Second)
	for {
		if _, err := os.Stat(ready); err == nil {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("fixture did not start")
		}
		time.Sleep(10 * time.Millisecond)
	}
	err = finishService(record, done, os.Interrupt, 0)
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || groupAlive(record.PGID) {
		t.Fatalf("forced stop err=%v, remaining group=%v", err, groupMembers(record.PGID))
	}
}

type blockedServiceOutput struct {
	entered chan struct{}
	release chan struct{}
}

func (output blockedServiceOutput) Write(data []byte) (int, error) {
	select {
	case output.entered <- struct{}{}:
	default:
	}
	<-output.release
	return len(data), nil
}

func TestServiceOutputDrainIsBounded(t *testing.T) {
	output := blockedServiceOutput{entered: make(chan struct{}, 1), release: make(chan struct{})}
	defer close(output.release)
	sp := Spec{Name: "output", Slug: "model", Dir: t.TempDir(), Env: os.Environ(), Command: []string{"/bin/sh", "-c", "printf output"}}
	_, done, err := launchService(sp, filepath.Join(t.TempDir(), "service.log"), ServiceIO{Stdout: output})
	if err != nil {
		t.Fatal(err)
	}
	select {
	case <-output.entered:
	case <-time.After(time.Second):
		t.Fatal("fixture did not write output")
	}
	select {
	case err := <-done:
		if err == nil || !strings.Contains(err.Error(), "output did not drain") {
			t.Fatalf("drain error=%v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("output drain did not stop")
	}
}

func TestRunServiceStartupInterrupt(t *testing.T) {
	for _, phase := range []string{"waiting", "preparing"} {
		t.Run(phase, func(t *testing.T) {
			executable, err := os.Executable()
			if err != nil {
				t.Fatal(err)
			}
			ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
			defer cancel()
			cmd := exec.CommandContext(ctx, executable, "-test.run=^TestRunServiceStartupInterruptHelper$")
			cmd.Env = append(os.Environ(), "ODS_TEST_STARTUP_INTERRUPT="+phase)
			output, err := cmd.CombinedOutput()
			if err != nil || !strings.Contains(string(output), "startup canceled") {
				t.Fatalf("interrupted startup: %v\n%s", err, output)
			}
		})
	}
}

func TestRunServiceStartupInterruptHelper(t *testing.T) {
	phase := os.Getenv("ODS_TEST_STARTUP_INTERRUPT")
	if phase == "" {
		return
	}
	marker := filepath.Join(t.TempDir(), "started")
	s, target, launch := runnerShellFixture(t, `printf started > "$1"`, marker)
	opts := ServiceOptions{PreferredPort: testBasePort + 200, LockWait: time.Second, StopTimeout: time.Second}
	if phase == "waiting" {
		release, err := s.Lock(context.Background(), "hold fixture", time.Second)
		if err != nil {
			t.Fatal(err)
		}
		done := make(chan error, 1)
		go func() { done <- s.RunService(context.Background(), target, launch, "model", opts) }()
		time.Sleep(100 * time.Millisecond)
		_ = syscall.Kill(os.Getpid(), syscall.SIGINT)
		select {
		case err = <-done:
			release()
		case <-time.After(400 * time.Millisecond):
			release()
			<-done
			t.Fatal("interrupt did not cancel the startup lock wait")
		}
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("startup error=%v, want context cancellation", err)
		}
	} else {
		opts.BeforeStart = func(ctx context.Context, _ Spec) error {
			_ = syscall.Kill(os.Getpid(), syscall.SIGINT)
			select {
			case <-ctx.Done():
			case <-time.After(300 * time.Millisecond):
			}
			return nil
		}
		if err := s.RunService(context.Background(), target, launch, "model", opts); !errors.Is(err, context.Canceled) {
			t.Fatalf("startup error=%v, want context cancellation", err)
		}
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("service launched after cancellation: %v", err)
	}
	fmt.Println("startup canceled")
}
