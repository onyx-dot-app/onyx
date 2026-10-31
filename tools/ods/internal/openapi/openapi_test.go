package openapi

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// chdirOutsideRepo makes an empty directory the working directory and stops
// git from finding a repository above it.
func chdirOutsideRepo(t *testing.T) {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(dir))
	t.Chdir(dir)
}

// fakePath replaces PATH with a directory that holds only git.
func fakePath(t *testing.T) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake python is a shell script")
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

// newRepo creates a git repository with a backend directory and makes it the
// working directory.
func newRepo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	gittest.Git(t, dir, "init", "-q")
	root, err := filepath.EvalSymlinks(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, "backend"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Chdir(root)
	return root
}

// writeExecutable writes a shell script. The script records its working
// directory and args in <path>.calls and its stdin in <path>.stdin.
func writeExecutable(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	script := "#!/bin/sh\n" +
		"printf '%s|%s\\n' \"$(pwd -P)\" \"$*\" >> \"$0.calls\"\n" +
		"while IFS= read -r l || [ -n \"$l\" ]; do printf '%s\\n' \"$l\"; done > \"$0.stdin\"\n" +
		body
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
}

func readLines(t *testing.T, path string) []string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
}

func TestResolvePath(t *testing.T) {
	root := newRepo(t)
	t.Chdir(filepath.Join(root, "backend"))
	abs := filepath.Join(root, "elsewhere", "x.json")

	cases := []struct {
		name, user, want string
	}{
		{"empty uses the default under the root", "", filepath.Join(root, "generated", "x.json")},
		{"absolute is kept", abs, abs},
		{"relative joins the working directory", "out/x.json", filepath.Join(root, "backend", "out", "x.json")},
	}
	for _, c := range cases {
		got, err := ResolvePath(c.user, filepath.Join("generated", "x.json"))
		if err != nil {
			t.Fatalf("%s: %v", c.name, err)
		}
		if got != c.want {
			t.Fatalf("%s: expected %q, got %q", c.name, c.want, got)
		}
	}
}

func TestResolvePath_defaultNeedsARepository(t *testing.T) {
	fakePath(t)
	chdirOutsideRepo(t)
	if _, err := ResolvePath("", "x.json"); err == nil || !strings.HasPrefix(err.Error(), "failed to find git root: ") {
		t.Fatalf("expected a git root error, got %v", err)
	}
}

func TestFindPythonBinary(t *testing.T) {
	t.Run("prefers the venv python", func(t *testing.T) {
		bin := fakePath(t)
		root := newRepo(t)
		venv := filepath.Join(root, ".venv", "bin", "python")
		writeExecutable(t, venv, "")
		writeExecutable(t, filepath.Join(bin, "python3"), "")

		if got, err := FindPythonBinary(); err != nil || got != venv {
			t.Fatalf("expected %q, got %q (%v)", venv, got, err)
		}
	})
	t.Run("prefers python3 over python on PATH", func(t *testing.T) {
		bin := fakePath(t)
		newRepo(t)
		writeExecutable(t, filepath.Join(bin, "python"), "")
		writeExecutable(t, filepath.Join(bin, "python3"), "")

		if got, err := FindPythonBinary(); err != nil || got != filepath.Join(bin, "python3") {
			t.Fatalf("expected python3 from PATH, got %q (%v)", got, err)
		}
	})
	t.Run("falls back to python outside a repository", func(t *testing.T) {
		bin := fakePath(t)
		chdirOutsideRepo(t)
		writeExecutable(t, filepath.Join(bin, "python"), "")

		if got, err := FindPythonBinary(); err != nil || got != filepath.Join(bin, "python") {
			t.Fatalf("expected python from PATH, got %q (%v)", got, err)
		}
	})
	t.Run("fails when no python exists", func(t *testing.T) {
		fakePath(t)
		newRepo(t)
		if _, err := FindPythonBinary(); err == nil || !strings.HasPrefix(err.Error(), "python not found") {
			t.Fatalf("expected a python not found error, got %v", err)
		}
	})
}

func TestRunScript_sendsTheEmbeddedScriptToPython(t *testing.T) {
	fakePath(t)
	root := newRepo(t)
	venv := filepath.Join(root, ".venv", "bin", "python")
	writeExecutable(t, venv, "")

	if err := RunScript([]string{"schema", "-o", "out.json"}); err != nil {
		t.Fatalf("RunScript: %v", err)
	}

	want := []string{filepath.Join(root, "backend") + "|- schema -o out.json"}
	if got := readLines(t, venv+".calls"); !slices.Equal(got, want) {
		t.Fatalf("expected %q, got %q", want, got)
	}
	stdin, err := os.ReadFile(venv + ".stdin")
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSuffix(string(stdin), "\n") != strings.TrimSuffix(embeddedScript, "\n") {
		t.Fatal("expected python to receive the embedded script on stdin")
	}
}

func TestRunScript_errors(t *testing.T) {
	t.Run("no python", func(t *testing.T) {
		fakePath(t)
		newRepo(t)
		if err := RunScript(nil); err == nil || !strings.HasPrefix(err.Error(), "python not found") {
			t.Fatalf("expected a python not found error, got %v", err)
		}
	})
	t.Run("outside a repository", func(t *testing.T) {
		bin := fakePath(t)
		chdirOutsideRepo(t)
		writeExecutable(t, filepath.Join(bin, "python3"), "")
		if err := RunScript(nil); err == nil || !strings.HasPrefix(err.Error(), "failed to find backend directory: ") {
			t.Fatalf("expected a backend directory error, got %v", err)
		}
		if _, err := os.Stat(filepath.Join(bin, "python3.calls")); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("expected python not to run, got %v", err)
		}
	})
	t.Run("python cannot start", func(t *testing.T) {
		fakePath(t)
		root := newRepo(t)
		venv := filepath.Join(root, ".venv", "bin", "python")
		writeExecutable(t, venv, "")
		if err := os.Chmod(venv, 0o644); err != nil {
			t.Fatal(err)
		}
		// Stat still finds the file, but exec needs an execute bit, even for root.
		if err := RunScript(nil); err == nil || !strings.HasPrefix(err.Error(), "failed to start python: ") {
			t.Fatalf("expected a start error, got %v", err)
		}
	})
	t.Run("python exit code is returned", func(t *testing.T) {
		fakePath(t)
		root := newRepo(t)
		writeExecutable(t, filepath.Join(root, ".venv", "bin", "python"), "exit 4\n")
		var exitErr *exec.ExitError
		if err := RunScript(nil); !errors.As(err, &exitErr) || exitErr.ExitCode() != 4 {
			t.Fatalf("expected exit code 4, got %v", err)
		}
	})
}

func TestGenerate_buildsScriptArgs(t *testing.T) {
	cases := []struct {
		name string
		run  func() error
		want string
	}{
		{"schema", func() error { return GenerateSchema("/s.json") }, "- schema -o /s.json"},
		{"client with output", func() error { return GenerateClient("/s.json", "/c") }, "- client -i /s.json -o /c"},
		{"client without output", func() error { return GenerateClient("/s.json", "") }, "- client -i /s.json"},
		{"all with client output", func() error { return GenerateAll("/s.json", "/c") }, "- all -o /s.json --client-output /c"},
		{"all without client output", func() error { return GenerateAll("/s.json", "") }, "- all -o /s.json"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			fakePath(t)
			root := newRepo(t)
			venv := filepath.Join(root, ".venv", "bin", "python")
			writeExecutable(t, venv, "")

			if err := c.run(); err != nil {
				t.Fatalf("run: %v", err)
			}
			want := []string{filepath.Join(root, "backend") + "|" + c.want}
			if got := readLines(t, venv+".calls"); !slices.Equal(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
		})
	}
}
