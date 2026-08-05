package markdown

import (
	"flag"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Goldens store ANSI-stripped output so they stay stable across color-palette
// tweaks and diff readably; SGR-level assertions live in render_test.go.
// Regenerate with: go test ./internal/markdown -update
var update = flag.Bool("update", false, "rewrite golden files")

func TestGolden(t *testing.T) {
	fixtures, err := filepath.Glob(filepath.Join("testdata", "*.md"))
	if err != nil {
		t.Fatal(err)
	}
	if len(fixtures) == 0 {
		t.Fatal("no fixtures found in testdata")
	}
	for _, fixture := range fixtures {
		name := strings.TrimSuffix(filepath.Base(fixture), ".md")
		t.Run(name, func(t *testing.T) {
			src, err := os.ReadFile(fixture)
			if err != nil {
				t.Fatal(err)
			}
			got := stripANSI(NewRenderer(60).Render(string(src)))
			goldenPath := filepath.Join("testdata", name+".golden")
			if *update {
				if err := os.WriteFile(goldenPath, []byte(got), 0o644); err != nil {
					t.Fatal(err)
				}
				return
			}
			want, err := os.ReadFile(goldenPath)
			if err != nil {
				t.Fatalf("missing golden file (run with -update): %v", err)
			}
			if got != string(want) {
				t.Errorf("output differs from %s:\n--- got ---\n%s\n--- want ---\n%s",
					goldenPath, got, want)
			}
		})
	}
}
