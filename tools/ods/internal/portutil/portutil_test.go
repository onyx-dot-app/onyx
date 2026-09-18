package portutil

import (
	"bytes"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"

	log "github.com/sirupsen/logrus"
)

func freePort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", ":0")
	if err != nil {
		t.Fatalf("failed to find a free port: %v", err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	_ = ln.Close()
	return port
}

// fakeTools puts shell scripts named after the map keys on a PATH that holds
// nothing else, so ProcessOnPort never reaches the host's lsof or ps. Each
// script appends its argv to <name>.args in the returned directory.
func fakeTools(t *testing.T, scripts map[string]string) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake tools are shell scripts")
	}
	dir := t.TempDir()
	for name, body := range scripts {
		script := "#!/bin/sh\necho \"$*\" >> \"$0.args\"\n" + body + "\n"
		if err := os.WriteFile(filepath.Join(dir, name), []byte(script), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", dir)
	return dir
}

func TestFindAvailable_returnsBaseWhenFree(t *testing.T) {
	base := freePort(t)
	port, err := FindAvailable(base, 100, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if port != base {
		t.Fatalf("expected %d, got %d", base, port)
	}
}

func TestFindAvailable_skipsOccupiedPort(t *testing.T) {
	base := freePort(t)
	ln, err := net.Listen("tcp", ":"+strconv.Itoa(base))
	if err != nil {
		t.Fatalf("failed to occupy port: %v", err)
	}
	defer func() { _ = ln.Close() }()

	fakeTools(t, map[string]string{"lsof": "echo 4242", "ps": "echo uvicorn"})
	var logs bytes.Buffer
	previous := log.StandardLogger().Out
	log.SetOutput(&logs)
	t.Cleanup(func() { log.SetOutput(previous) })

	port, err := FindAvailable(base, 100, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if port <= base {
		t.Fatalf("expected port > %d (occupied), got %d", base, port)
	}
	want := "Port " + strconv.Itoa(base) + " is in use by uvicorn (PID 4242), using available port " + strconv.Itoa(port) + " instead."
	if !strings.Contains(logs.String(), want) {
		t.Fatalf("expected warning %q, got %q", want, logs.String())
	}
}

func TestFindAvailable_skipsClaimedPort(t *testing.T) {
	base := freePort(t)
	claimed := map[int]bool{base: true}
	port, err := FindAvailable(base, 100, claimed)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if port <= base {
		t.Fatalf("expected port > %d (claimed), got %d", base, port)
	}
}

func TestFindAvailable_errorWhenAllOccupied(t *testing.T) {
	base := freePort(t)
	maxRange := 100

	var listeners []net.Listener
	defer func() {
		for _, ln := range listeners {
			_ = ln.Close()
		}
	}()

	for i := 0; i < maxRange; i++ {
		ln, err := net.Listen("tcp", ":"+strconv.Itoa(base+i))
		if err != nil {
			// The port is already held by another process. That still
			// counts as occupied for the purposes of this test, so leave
			// it be rather than failing.
			continue
		}
		listeners = append(listeners, ln)
	}

	_, err := FindAvailable(base, maxRange, nil)
	if err == nil {
		t.Fatal("expected error when all ports occupied, got nil")
	}
}

func TestProcessOnPort(t *testing.T) {
	tests := []struct {
		name   string
		lsof   string
		ps     string
		want   string
		wantPs string // empty when ps must not run
	}{
		{name: "names the first listening process", lsof: `printf '123\n456\n'`, ps: "echo ' uvicorn '", want: "uvicorn (PID 123)", wantPs: "-p 123 -o comm="},
		{name: "falls back to the PID when ps fails", lsof: "echo 123", ps: "exit 1", want: "process (PID 123)", wantPs: "-p 123 -o comm="},
		{name: "falls back to the PID when ps prints nothing", lsof: "echo 123", ps: "true", want: "process (PID 123)", wantPs: "-p 123 -o comm="},
		{name: "unknown when lsof fails", lsof: "exit 1", ps: "echo never", want: "an unknown process"},
		{name: "unknown when nothing listens", lsof: "true", ps: "echo never", want: "an unknown process"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := fakeTools(t, map[string]string{"lsof": tt.lsof, "ps": tt.ps})

			if got := ProcessOnPort(8080); got != tt.want {
				t.Fatalf("expected %q, got %q", tt.want, got)
			}
			lsofArgs, err := os.ReadFile(filepath.Join(dir, "lsof.args"))
			if err != nil {
				t.Fatalf("lsof was not run: %v", err)
			}
			if got := strings.TrimSpace(string(lsofArgs)); got != "-i :8080 -t" {
				t.Fatalf("expected lsof args %q, got %q", "-i :8080 -t", got)
			}
			psArgs, err := os.ReadFile(filepath.Join(dir, "ps.args"))
			if tt.wantPs == "" {
				if err == nil {
					t.Fatalf("ps should not run when lsof finds no process, got args %q", psArgs)
				}
				return
			}
			if got := strings.TrimSpace(string(psArgs)); got != tt.wantPs {
				t.Fatalf("expected ps args %q, got %q", tt.wantPs, got)
			}
		})
	}
}
