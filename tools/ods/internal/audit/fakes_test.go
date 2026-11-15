package audit

import (
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// fakeBinDir creates a directory of fake executables and puts it at the front of
// PATH, so the real git stays reachable behind it.
func fakeBinDir(t *testing.T) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake binaries are shell scripts")
	}
	dir := t.TempDir()
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	return dir
}

// writeFakeCommand writes an executable shell script named name into dir. Each
// call appends its argument count and arguments, each NUL-terminated, to
// <dir>/<name>.args before running body. The returned function decodes the log
// into one argv per call.
func writeFakeCommand(t *testing.T, dir, name, body string) func() [][]string {
	t.Helper()
	argsLog := filepath.Join(dir, name+".args")
	script := "#!/bin/sh\nprintf '%s\\0' \"$#\" \"$@\" >> \"$0.args\"\n" + body + "\n"
	if err := os.WriteFile(filepath.Join(dir, name), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return func() [][]string {
		data, err := os.ReadFile(argsLog)
		if os.IsNotExist(err) {
			return nil
		}
		if err != nil {
			t.Fatal(err)
		}
		fields := strings.Split(strings.TrimSuffix(string(data), "\x00"), "\x00")
		var calls [][]string
		for len(fields) > 0 {
			n, err := strconv.Atoi(fields[0])
			if err != nil || n > len(fields)-1 {
				t.Fatalf("malformed args log %q", data)
			}
			calls = append(calls, fields[1:1+n])
			fields = fields[1+n:]
		}
		return calls
	}
}

// writeFixture writes content to a file in dir and returns its path, for fake
// commands to cat.
func writeFixture(t *testing.T, dir, name, content string) string {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

// chdirNewRepo makes a fresh git repository the working directory and returns
// its root as git reports it.
func chdirNewRepo(t *testing.T) string {
	t.Helper()
	gittest.IsolateConfig(t)
	dir := t.TempDir()
	gittest.Git(t, dir, "init", "-q", "-b", "main")
	t.Chdir(dir)
	return gittest.Git(t, dir, "rev-parse", "--show-toplevel")
}

// chdirOutsideRepo makes a directory that is not inside any git repository the
// working directory.
func chdirOutsideRepo(t *testing.T) {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(dir))
	t.Chdir(dir)
}
