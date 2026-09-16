package cmd

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// devtoolRepo creates an empty git repository, makes it the working directory,
// and returns its root as git reports it.
func devtoolRepo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	gittest.Git(t, dir, "init", "-q")
	t.Chdir(dir)
	root, err := filepath.EvalSymlinks(dir)
	if err != nil {
		t.Fatal(err)
	}
	return root
}

// devtoolBinDir replaces PATH with a new directory that holds only git, so any
// other tool a command starts must be a fake that the test provides.
func devtoolBinDir(t *testing.T) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake tools are shell scripts")
	}
	git, err := exec.LookPath("git")
	if err != nil {
		t.Fatalf("git is required: %v", err)
	}
	dir := t.TempDir()
	if err := os.Symlink(git, filepath.Join(dir, "git")); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
	return dir
}

// devtoolFakeTool writes an executable script called name into binDir. Each
// run appends its working dir, argument count and arguments, each
// NUL-terminated, to the returned call log, then runs body.
func devtoolFakeTool(t *testing.T, binDir, name, body string) string {
	t.Helper()
	calls := filepath.Join(binDir, name+".calls")
	script := "#!/bin/sh\nprintf '%s\\0' \"$(pwd -P)\" \"$#\" \"$@\" >> \"$0.calls\"\n" + body
	if err := os.WriteFile(filepath.Join(binDir, name), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return calls
}

// devtoolCall is one recorded run of a fake tool.
type devtoolCall struct {
	Dir  string
	Args []string
}

// devtoolCalls returns the invocations recorded in a call log, in order.
func devtoolCalls(t *testing.T, calls string) []devtoolCall {
	t.Helper()
	data, err := os.ReadFile(calls)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	fields := strings.Split(strings.TrimSuffix(string(data), "\x00"), "\x00")
	var got []devtoolCall
	for len(fields) > 0 {
		if len(fields) < 2 {
			t.Fatalf("malformed call log %q", data)
		}
		n, err := strconv.Atoi(fields[1])
		if err != nil || n > len(fields)-2 {
			t.Fatalf("malformed call log %q", data)
		}
		got = append(got, devtoolCall{Dir: fields[0], Args: fields[2 : 2+n]})
		fields = fields[2+n:]
	}
	return got
}

// devtoolUnsetenv removes key for the rest of the test and restores it after.
func devtoolUnsetenv(t *testing.T, key string) {
	t.Helper()
	t.Setenv(key, "")
	if err := os.Unsetenv(key); err != nil {
		t.Fatal(err)
	}
}
