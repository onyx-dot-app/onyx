package cmd

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// gitrelFakeGH puts a fake gh first on PATH, followed by the system
// directories so the code under test still runs the real git. Every call
// records its argv. caseArms are sh case arms matched against "$*"; a call no
// arm matches prints nothing and exits 0. It returns a function that reads the
// recorded calls.
func gitrelFakeGH(t *testing.T, caseArms string) func() [][]string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake gh is a shell script")
	}
	dir := t.TempDir()
	record := filepath.Join(dir, "calls")
	// \037 ends an argument and \036 ends a call, so arguments may hold
	// newlines.
	script := "#!/bin/sh\n" +
		"{ for a in \"$@\"; do printf '%s\\037' \"$a\"; done; printf '\\036'; } >> \"${0%/*}/calls\"\n" +
		"case \"$*\" in\n" +
		"--version) exit 0 ;;\n" +
		caseArms + "\n" +
		"esac\n"
	if err := os.WriteFile(filepath.Join(dir, "gh"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))

	return func() [][]string {
		t.Helper()
		data, err := os.ReadFile(record)
		if os.IsNotExist(err) {
			return nil
		}
		if err != nil {
			t.Fatal(err)
		}
		calls := [][]string{}
		for _, call := range strings.Split(string(data), "\036") {
			if call == "" {
				continue
			}
			calls = append(calls, strings.Split(strings.TrimSuffix(call, "\037"), "\037"))
		}
		return calls
	}
}

// gitrelCallsWithPrefix returns the recorded calls whose argv starts with
// prefix.
func gitrelCallsWithPrefix(calls [][]string, prefix ...string) [][]string {
	matched := [][]string{}
	for _, call := range calls {
		if len(call) >= len(prefix) && slices.Equal(call[:len(prefix)], prefix) {
			matched = append(matched, call)
		}
	}
	return matched
}

// gitrelAssertArgs fails the test unless got equals want.
func gitrelAssertArgs(t *testing.T, got, want []string) {
	t.Helper()
	if !slices.Equal(got, want) {
		t.Fatalf("expected args\n%q\ngot\n%q", want, got)
	}
}

// gitrelCommit writes content to filename and commits it with msg in dir,
// returning the commit SHA.
func gitrelCommit(t *testing.T, dir, filename, content, msg string) string {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, filename), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	gittest.Git(t, dir, "add", filename)
	gittest.Git(t, dir, "commit", "--quiet", "-m", msg)
	return gittest.Git(t, dir, "rev-parse", "HEAD")
}

// gitrelRefExists reports whether ref resolves in the repository at dir.
func gitrelRefExists(dir, ref string) bool {
	cmd := exec.Command("git", "rev-parse", "-q", "--verify", ref)
	cmd.Dir = dir
	return cmd.Run() == nil
}

// gitrelReadFile returns the content of a file in dir.
func gitrelReadFile(t *testing.T, dir, name string) string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(dir, name))
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

// gitrelHooks points the repository at dir to a fresh hooks directory holding
// the given hook scripts, so a global core.hooksPath cannot interfere.
func gitrelHooks(t *testing.T, dir string, hooks map[string]string) {
	t.Helper()
	hookDir := t.TempDir()
	for name, script := range hooks {
		if err := os.WriteFile(filepath.Join(hookDir, name), []byte(script), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	gittest.Git(t, dir, "config", "core.hooksPath", hookDir)
}

// gitrelChdirOutsideRepo makes an empty directory the working directory and
// stops git from finding a repository above it.
func gitrelChdirOutsideRepo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(dir))
	t.Chdir(dir)
	return dir
}
