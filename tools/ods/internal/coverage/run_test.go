package coverage

import (
	"os"
	"path/filepath"
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
	if got := err.Error(); got != "go test exited with code 2" {
		t.Fatalf("unexpected message: %q", got)
	}
}
