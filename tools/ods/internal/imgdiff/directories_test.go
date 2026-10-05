package imgdiff

import (
	"image/color"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCompare_reportsUndecodableImages(t *testing.T) {
	dir := t.TempDir()
	valid := filepath.Join(dir, "valid.png")
	createTestPNG(t, valid, 2, 2, color.White)
	corrupt := filepath.Join(dir, "corrupt.png")
	if err := os.WriteFile(corrupt, []byte("not a png"), 0o644); err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name     string
		baseline string
		current  string
		want     string
	}{
		{"missing baseline", filepath.Join(dir, "missing.png"), valid, "failed to decode baseline"},
		{"corrupt current", valid, corrupt, "failed to decode current"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := Compare(tt.baseline, tt.current, 0.2)
			if err == nil || !strings.HasPrefix(err.Error(), tt.want) {
				t.Fatalf("expected %q, got %v", tt.want, err)
			}
		})
	}
}

// Changed screenshots come first, largest diff first; the rest sort by status
// and then by name. Subdirectories and non-PNG files are ignored.
func TestCompareDirectories_ordersResults(t *testing.T) {
	baselineDir := filepath.Join(t.TempDir(), "baseline")
	currentDir := filepath.Join(t.TempDir(), "current")
	white := color.RGBA{R: 255, G: 255, B: 255, A: 255}
	red := color.RGBA{R: 255, A: 255}

	for _, name := range []string{"small.png", "big.png", "b-same.png", "a-same.png", "y-gone.png", "x-gone.png"} {
		createTestPNG(t, filepath.Join(baselineDir, name), 10, 10, white)
	}
	createTestPNGWithBlock(t, filepath.Join(currentDir, "small.png"), 10, 10, white, red, 0, 0, 1, 1)
	createTestPNGWithBlock(t, filepath.Join(currentDir, "big.png"), 10, 10, white, red, 0, 0, 5, 5)
	createTestPNG(t, filepath.Join(currentDir, "b-same.png"), 10, 10, white)
	createTestPNG(t, filepath.Join(currentDir, "a-same.png"), 10, 10, white)
	createTestPNG(t, filepath.Join(currentDir, "Z-NEW.PNG"), 10, 10, white)
	createTestPNG(t, filepath.Join(currentDir, "nested.png", "inner.png"), 10, 10, white)
	if err := os.WriteFile(filepath.Join(currentDir, "notes.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}

	results, err := CompareDirectories(baselineDir, currentDir, 0.2)
	if err != nil {
		t.Fatalf("CompareDirectories failed: %v", err)
	}

	var got []string
	for _, r := range results {
		got = append(got, r.Status.String()+" "+r.Name)
	}
	want := []string{
		"changed big.png", "changed small.png",
		"added Z-NEW.PNG",
		"removed x-gone.png", "removed y-gone.png",
		"unchanged a-same.png", "unchanged b-same.png",
	}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestCompareDirectories_reportsFailures(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "file")
	if err := os.WriteFile(file, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	goodDir := filepath.Join(dir, "good")
	createTestPNG(t, filepath.Join(goodDir, "page.png"), 2, 2, color.White)
	corruptDir := filepath.Join(dir, "corrupt")
	if err := os.MkdirAll(corruptDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(corruptDir, "page.png"), []byte("nope"), 0o644); err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name     string
		baseline string
		current  string
		want     string
	}{
		{"baseline is a file", file, goodDir, "failed to list baseline directory"},
		{"current is a file", goodDir, file, "failed to list current directory"},
		{"corrupt screenshot", goodDir, corruptDir, "failed to compare page.png"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := CompareDirectories(tt.baseline, tt.current, 0.2)
			if err == nil || !strings.HasPrefix(err.Error(), tt.want) {
				t.Fatalf("expected %q, got %v", tt.want, err)
			}
		})
	}
}

// A missing directory counts as empty, so every baseline screenshot is removed.
func TestCompareDirectories_missingCurrentMeansRemoved(t *testing.T) {
	baselineDir := t.TempDir()
	createTestPNG(t, filepath.Join(baselineDir, "page.png"), 2, 2, color.White)

	results, err := CompareDirectories(baselineDir, filepath.Join(t.TempDir(), "missing"), 0.2)
	if err != nil {
		t.Fatalf("CompareDirectories failed: %v", err)
	}

	if len(results) != 1 || results[0].Status != StatusRemoved || results[0].CurrentPath != "" {
		t.Fatalf("expected one removed result, got %+v", results)
	}
}
