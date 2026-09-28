package coverage

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func writeGoMod(t *testing.T, contents string) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "go.mod"), []byte(contents), 0644); err != nil {
		t.Fatalf("failed to write go.mod: %v", err)
	}
	return dir
}

func TestModulePath_readsTheModuleLine(t *testing.T) {
	dir := writeGoMod(t, "module example.com/m/tools/ods\n\ngo 1.26.4\n")

	path, err := ModulePath(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if path != "example.com/m/tools/ods" {
		t.Fatalf("expected the module path, got %q", path)
	}
}

func TestModulePath_missingGoMod(t *testing.T) {
	if _, err := ModulePath(t.TempDir()); err == nil {
		t.Fatal("expected an error when go.mod is missing")
	}
}

func TestModulePath_noModuleDeclaration(t *testing.T) {
	dir := writeGoMod(t, "go 1.26.4\n")

	if _, err := ModulePath(dir); err == nil {
		t.Fatal("expected an error when go.mod declares no module")
	}
}

func TestExitError_reportsTheCode(t *testing.T) {
	err := &ExitError{Code: 2}
	if got := err.Error(); got != "the measurement exited with code 2" {
		t.Fatalf("unexpected message: %q", got)
	}
}

// fakeGo puts a go on PATH that runs script.
func fakeGo(t *testing.T, script string) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake go is a shell script")
	}
	bin := t.TempDir()
	if err := os.WriteFile(filepath.Join(bin, "go"), []byte("#!/bin/sh\n"+script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
}

func TestRun_failuresBeforeAndDuringTheTests(t *testing.T) {
	t.Run("failed tests pass the exit code through", func(t *testing.T) {
		fakeGo(t, "exit 4\n")
		dir := writeGoMod(t, "module example.com/m\n")

		_, err := Run(RunOptions{ModuleDir: dir, ProfilePath: filepath.Join(dir, "cover.out")})

		var exitErr *ExitError
		if !errors.As(err, &exitErr) || exitErr.Code != 4 {
			t.Fatalf("expected exit code 4, got %v", err)
		}
	})

	t.Run("missing go is not an exit code", func(t *testing.T) {
		t.Setenv("PATH", t.TempDir())
		dir := writeGoMod(t, "module example.com/m\n")

		_, err := Run(RunOptions{ModuleDir: dir, ProfilePath: filepath.Join(dir, "cover.out")})

		var exitErr *ExitError
		if err == nil || errors.As(err, &exitErr) {
			t.Fatalf("expected a plain error, got %v", err)
		}
	})

	t.Run("missing go.mod runs nothing", func(t *testing.T) {
		record := filepath.Join(t.TempDir(), "ran")
		fakeGo(t, "touch "+record+"\n")

		if _, err := Run(RunOptions{ModuleDir: t.TempDir(), ProfilePath: filepath.Join(t.TempDir(), "c.out")}); err == nil {
			t.Fatal("expected an error without a go.mod")
		}
		if _, err := os.Stat(record); !os.IsNotExist(err) {
			t.Fatalf("expected go not to run, got %v", err)
		}
	})

	t.Run("profile directory under a file", func(t *testing.T) {
		dir := writeGoMod(t, "module example.com/m\n")

		_, err := Run(RunOptions{ModuleDir: dir, ProfilePath: filepath.Join(dir, "go.mod", "c.out")})
		if err == nil || !strings.HasPrefix(err.Error(), "create profile directory: ") {
			t.Fatalf("expected a profile directory error, got %v", err)
		}
	})
}
