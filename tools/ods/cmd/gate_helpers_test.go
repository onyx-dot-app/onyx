package cmd

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// gateProfile is a profile of example.com/m with one package, pkg, at 50%.
const gateProfile = "mode: set\nexample.com/m/pkg/a.go:1.1,2.2 1 1\nexample.com/m/pkg/a.go:3.1,4.2 1 0\n"

// gateRepo creates a git repository holding a tools/ods module named
// example.com/m, commits it, and changes into its root. It returns the root.
func gateRepo(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	gittest.Git(t, root, "init", "-q", "-b", "main")
	gittest.Git(t, root, "config", "user.email", "test@example.com")
	gittest.Git(t, root, "config", "user.name", "Test")
	gittest.Git(t, root, "config", "commit.gpgsign", "false")
	gateWriteFile(t, filepath.Join(root, "tools", "ods", "go.mod"), "module example.com/m\n")
	gittest.Git(t, root, "add", ".")
	gittest.Git(t, root, "commit", "-q", "-m", "init")
	t.Chdir(root)
	return root
}

// gateFakeBin puts an executable shell script called name first on PATH, so
// real tools such as git stay reachable.
func gateFakeBin(t *testing.T, name, script string) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake tool is a shell script")
	}
	dir := t.TempDir()
	gateWriteFile(t, filepath.Join(dir, name), "#!/bin/sh\n"+script)
	if err := os.Chmod(filepath.Join(dir, name), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
}

// gateTempDir points TMPDIR at a fresh directory and returns it.
func gateTempDir(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("TMPDIR", dir)
	return dir
}

func gateWriteFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func gateReadFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

// gateLines reads a file the fake tools record into, one entry per line.
func gateLines(t *testing.T, path string) []string {
	t.Helper()
	return strings.Split(strings.TrimRight(gateReadFile(t, path), "\n"), "\n")
}
