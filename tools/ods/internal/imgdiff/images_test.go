package imgdiff

import (
	"image"
	"image/color"
	"os"
	"path/filepath"
	"testing"
)

// buildResults produces one result per status against real PNG files on disk,
// so WriteImages has something to copy.
func buildResults(t *testing.T, srcDir string) []Result {
	t.Helper()

	changedBaseline := filepath.Join(srcDir, "changed-baseline.png")
	changedCurrent := filepath.Join(srcDir, "changed-current.png")
	addedCurrent := filepath.Join(srcDir, "added-current.png")
	removedBaseline := filepath.Join(srcDir, "removed-baseline.png")
	unchangedBaseline := filepath.Join(srcDir, "unchanged-baseline.png")
	unchangedCurrent := filepath.Join(srcDir, "unchanged-current.png")

	createTestPNG(t, changedBaseline, 4, 4, color.White)
	createTestPNG(t, changedCurrent, 4, 4, color.Black)
	createTestPNG(t, addedCurrent, 4, 4, color.Black)
	createTestPNG(t, removedBaseline, 4, 4, color.White)
	createTestPNG(t, unchangedBaseline, 4, 4, color.White)
	createTestPNG(t, unchangedCurrent, 4, 4, color.White)

	return []Result{
		{
			Name:         "changed.png",
			Status:       StatusChanged,
			DiffPercent:  12.5,
			BaselinePath: changedBaseline,
			CurrentPath:  changedCurrent,
			DiffImage:    image.NewRGBA(image.Rect(0, 0, 4, 4)),
		},
		{
			Name:        "added.png",
			Status:      StatusAdded,
			CurrentPath: addedCurrent,
		},
		{
			Name:         "removed.png",
			Status:       StatusRemoved,
			BaselinePath: removedBaseline,
		},
		{
			Name:         "unchanged.png",
			Status:       StatusUnchanged,
			BaselinePath: unchangedBaseline,
			CurrentPath:  unchangedCurrent,
		},
	}
}

func TestWriteImages(t *testing.T) {
	tmp := t.TempDir()
	srcDir := filepath.Join(tmp, "src")
	outDir := filepath.Join(tmp, "report")

	if err := WriteImages(buildResults(t, srcDir), outDir); err != nil {
		t.Fatalf("WriteImages failed: %v", err)
	}

	tests := []struct {
		path string
		want bool
	}{
		// Changed screenshots get all three images.
		{filepath.Join("baseline", "changed.png"), true},
		{filepath.Join("current", "changed.png"), true},
		{filepath.Join("diff", "changed.png"), true},
		// Added screenshots have no baseline.
		{filepath.Join("current", "added.png"), true},
		{filepath.Join("baseline", "added.png"), false},
		{filepath.Join("diff", "added.png"), false},
		// Removed screenshots have no current.
		{filepath.Join("baseline", "removed.png"), true},
		{filepath.Join("current", "removed.png"), false},
		{filepath.Join("diff", "removed.png"), false},
		// Unchanged screenshots are skipped entirely.
		{filepath.Join("baseline", "unchanged.png"), false},
		{filepath.Join("current", "unchanged.png"), false},
		{filepath.Join("diff", "unchanged.png"), false},
	}

	for _, tt := range tests {
		full := filepath.Join(outDir, ImagesDirName, tt.path)
		_, err := os.Stat(full)
		if tt.want && err != nil {
			t.Errorf("expected %s to exist, got error: %v", tt.path, err)
		}
		if !tt.want && err == nil {
			t.Errorf("expected %s to be absent, but it exists", tt.path)
		}
	}
}

func TestWriteImages_CopiesContent(t *testing.T) {
	tmp := t.TempDir()
	srcDir := filepath.Join(tmp, "src")
	outDir := filepath.Join(tmp, "report")

	results := buildResults(t, srcDir)
	if err := WriteImages(results, outDir); err != nil {
		t.Fatalf("WriteImages failed: %v", err)
	}

	want, err := os.ReadFile(results[0].BaselinePath)
	if err != nil {
		t.Fatalf("failed to read source: %v", err)
	}
	got, err := os.ReadFile(filepath.Join(outDir, ImagesDirName, "baseline", "changed.png"))
	if err != nil {
		t.Fatalf("failed to read copy: %v", err)
	}
	if string(got) != string(want) {
		t.Error("copied baseline image does not match the source")
	}
}

func TestWriteImages_NoDifferences(t *testing.T) {
	tmp := t.TempDir()
	outDir := filepath.Join(tmp, "report")

	if err := WriteImages(nil, outDir); err != nil {
		t.Fatalf("WriteImages failed: %v", err)
	}

	// Nothing to write means no images directory at all.
	if _, err := os.Stat(filepath.Join(outDir, ImagesDirName)); !os.IsNotExist(err) {
		t.Errorf("expected no images directory, got err=%v", err)
	}
}
