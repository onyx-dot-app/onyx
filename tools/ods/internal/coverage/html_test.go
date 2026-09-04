package coverage

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Builds a one-package module, runs its tests for a profile, and renders it.
// This calls the real go toolchain, so it is the one test here that needs it.
func TestWriteHTML_rendersTheProfile(t *testing.T) {
	dir := t.TempDir()
	files := map[string]string{
		"go.mod":       "module example.com/tiny\n\ngo 1.21\n",
		"tiny.go":      "package tiny\n\nfunc Yes() bool { return true }\n",
		"tiny_test.go": "package tiny\n\nimport \"testing\"\n\nfunc TestYes(t *testing.T) { if !Yes() { t.Fatal() } }\n",
	}
	for name, contents := range files {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(contents), 0644); err != nil {
			t.Fatalf("failed to write %s: %v", name, err)
		}
	}

	profilePath := filepath.Join(dir, "out", "coverage.out")
	if _, err := Run(RunOptions{ModuleDir: dir, ProfilePath: profilePath}); err != nil {
		t.Fatalf("failed to run the tests: %v", err)
	}

	htmlPath := filepath.Join(dir, "out", "html", "coverage.html")
	if err := WriteHTML(dir, profilePath, htmlPath); err != nil {
		t.Fatalf("failed to render html: %v", err)
	}

	html, err := os.ReadFile(htmlPath)
	if err != nil {
		t.Fatalf("failed to read the html: %v", err)
	}
	if !strings.Contains(string(html), "func Yes()") {
		t.Fatalf("expected the source in the html, got %d bytes", len(html))
	}
}
