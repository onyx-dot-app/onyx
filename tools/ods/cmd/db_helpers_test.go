package cmd

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// dbCallSeparator ends the argv of one recorded fake-binary invocation.
const dbCallSeparator = "--end-of-call--"

// dbPostgresEnv lists every POSTGRES_* variable the db commands read. The dev
// container exports them, so each test clears them first.
var dbPostgresEnv = []string{"POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"}

// dbSetup isolates a db command test: fake binaries only on PATH, no
// POSTGRES_* variables, and data and config directories in a temp dir. It
// returns the directory on PATH.
func dbSetup(t *testing.T) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake binaries are shell scripts")
	}
	for _, key := range dbPostgresEnv {
		t.Setenv(key, "")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_DATA_HOME", filepath.Join(home, "data"))
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(home, "config"))
	binDir := t.TempDir()
	t.Setenv("PATH", binDir)
	return binDir
}

// dbFakeBinary writes a shell script called name to binDir. The script records
// its argv, one argument per line, then runs behaviour. It returns a function
// that reads the recorded invocations.
func dbFakeBinary(t *testing.T, binDir, name, behaviour string) func() [][]string {
	t.Helper()
	record := filepath.Join(binDir, name+".calls")
	script := "#!/bin/sh\n" +
		"for arg in \"$@\"; do printf '%s\\n' \"$arg\" >> \"$0.calls\"; done\n" +
		"printf '%s\\n' '" + dbCallSeparator + "' >> \"$0.calls\"\n" +
		behaviour + "\n"
	if err := os.WriteFile(filepath.Join(binDir, name), []byte(script), 0o755); err != nil {
		t.Fatalf("Failed to write fake %s: %v", name, err)
	}
	return func() [][]string {
		data, err := os.ReadFile(record)
		if os.IsNotExist(err) {
			return nil
		}
		if err != nil {
			t.Fatalf("Failed to read %s calls: %v", name, err)
		}
		var calls [][]string
		current := []string{}
		for _, line := range strings.Split(strings.TrimSuffix(string(data), "\n"), "\n") {
			if line == dbCallSeparator {
				calls = append(calls, current)
				current = []string{}
				continue
			}
			current = append(current, line)
		}
		return calls
	}
}

// dbFakeDocker installs a fake docker that reports every container as
// running. behaviour runs first and can exit early to override that. It
// returns the name the commands pick for the PostgreSQL container and a
// function that reads the recorded invocations.
func dbFakeDocker(t *testing.T, binDir, behaviour string) (string, func() [][]string) {
	t.Helper()
	calls := dbFakeBinary(t, binDir, "docker", behaviour+"\n"+
		`if [ "$1" = inspect ]; then echo true; fi`)
	return docker.ProjectName() + "-relational_db-1", calls
}

// dbDockerExecs keeps only the `docker exec` and `docker cp` invocations,
// dropping the container lookups.
func dbDockerExecs(calls [][]string) [][]string {
	var kept [][]string
	for _, call := range calls {
		if len(call) > 0 && (call[0] == "exec" || call[0] == "cp") {
			kept = append(kept, call)
		}
	}
	return kept
}

// dbCaptureLog sends logrus output to a buffer for the rest of the test.
func dbCaptureLog(t *testing.T) *bytes.Buffer {
	t.Helper()
	var buf bytes.Buffer
	previous := log.StandardLogger().Out
	log.SetOutput(&buf)
	t.Cleanup(func() { log.SetOutput(previous) })
	return &buf
}

// dbAssertCalls fails the test unless got equals want, call by call.
func dbAssertCalls(t *testing.T, got, want [][]string) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("expected %d calls, got %d:\n%s", len(want), len(got), dbFormatCalls(got))
	}
	for i := range want {
		if strings.Join(got[i], "\x00") != strings.Join(want[i], "\x00") {
			t.Fatalf("call %d: expected %q, got %q", i, want[i], got[i])
		}
	}
}

func dbFormatCalls(calls [][]string) string {
	lines := make([]string, len(calls))
	for i, call := range calls {
		lines[i] = strings.Join(call, " ")
	}
	return strings.Join(lines, "\n")
}

// dbGitPath returns the real git binary. Call it before dbSetup replaces PATH.
func dbGitPath(t *testing.T) string {
	t.Helper()
	gitPath, err := exec.LookPath("git")
	if err != nil {
		t.Skipf("git is not installed: %v", err)
	}
	return gitPath
}

// dbFakeRepo creates a git repository with a backend directory, makes it the
// working directory, and links git into binDir so the code under test can
// find the repository. It returns the repository root.
func dbFakeRepo(t *testing.T, binDir, gitPath string) string {
	t.Helper()
	if err := os.Symlink(gitPath, filepath.Join(binDir, "git")); err != nil {
		t.Fatalf("Failed to link git: %v", err)
	}
	root := filepath.Join(t.TempDir(), "onyx")
	if err := os.MkdirAll(filepath.Join(root, "backend"), 0o755); err != nil {
		t.Fatalf("Failed to create the backend directory: %v", err)
	}
	gittest.Git(t, root, "init", "--quiet")
	t.Chdir(root)
	return root
}
