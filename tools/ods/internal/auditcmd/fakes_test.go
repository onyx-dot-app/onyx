package auditcmd

import (
	"os"
	"path/filepath"
	"runtime"
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
// call appends its arguments as one line to <dir>/<name>.args before running
// body, and the returned function reads those lines back. The script finds the
// log through $0, so the temp dir path never goes into the script text.
func writeFakeCommand(t *testing.T, dir, name, body string) func() []string {
	t.Helper()
	argsLog := filepath.Join(dir, name+".args")
	script := "#!/bin/sh\necho \"$*\" >> \"$0.args\"\n" + body + "\n"
	if err := os.WriteFile(filepath.Join(dir, name), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return func() []string {
		data, err := os.ReadFile(argsLog)
		if os.IsNotExist(err) {
			return nil
		}
		if err != nil {
			t.Fatal(err)
		}
		return strings.Split(strings.TrimSpace(string(data)), "\n")
	}
}

// writeFixture writes content to a file in dir and returns its path.
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

// chdirNewRepo makes a fresh git repository the working directory. Global and
// system git config are hidden so only the repository's own config applies.
func chdirNewRepo(t *testing.T) string {
	t.Helper()
	gittest.IsolateConfig(t)
	dir := t.TempDir()
	gittest.Git(t, dir, "init", "-q", "-b", "main")
	t.Chdir(dir)
	return dir
}

// fakeDependabot installs a gh that prints alertsJSON.
func fakeDependabot(t *testing.T, bin, alertsJSON string) {
	t.Helper()
	writeFixture(t, bin, "alerts.json", alertsJSON)
	writeFakeCommand(t, bin, "gh", `cat "$(dirname "$0")/alerts.json"`)
}
