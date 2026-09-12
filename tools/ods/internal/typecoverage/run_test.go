package typecoverage

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/coverage"
)

// fakeBun puts a bun on PATH that runs script, then returns a web dir and an
// absolute output path.
func fakeBun(t *testing.T, script string) (string, string) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake bun is a shell script")
	}
	binDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(binDir, "bun"), []byte("#!/bin/sh\n"+script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", binDir)
	return t.TempDir(), filepath.Join(t.TempDir(), "out", "type-coverage.json")
}

func TestRun_parsesTheScriptOutput(t *testing.T) {
	webDir, output := fakeBun(t, `
[ "$*" = "run types:check -- --output $5" ] || { echo "unexpected args: $*" >&2; exit 9; }
printf '%s' '{"files":[{"file":"src/a.ts","correct":1,"total":2}]}' > "$5"
`)

	files, err := Run(RunOptions{WebDir: webDir, OutputPath: output})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if len(files) != 1 || files[0] != (FileCount{File: "src/a.ts", Correct: 1, Total: 2}) {
		t.Fatalf("unexpected files: %+v", files)
	}
}

func TestRun_passesTheExitCodeThrough(t *testing.T) {
	webDir, output := fakeBun(t, "exit 3\n")

	_, err := Run(RunOptions{WebDir: webDir, OutputPath: output})

	var exitErr *coverage.ExitError
	if !errors.As(err, &exitErr) || exitErr.Code != 3 {
		t.Fatalf("expected exit code 3, got %v", err)
	}
}

func TestRun_rejectsARelativeOutputPath(t *testing.T) {
	if _, err := Run(RunOptions{WebDir: t.TempDir(), OutputPath: "out.json"}); err == nil {
		t.Fatal("expected an error for a relative output path")
	}
}
