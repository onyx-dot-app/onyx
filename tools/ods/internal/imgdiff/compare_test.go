package imgdiff

import (
	"image"
	"image/color"
	"image/png"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// createTestPNG creates a solid-color PNG file at the given path.
func createTestPNG(t *testing.T, path string, width, height int, c color.Color) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatalf("failed to create dir: %v", err)
	}
	img := image.NewRGBA(image.Rect(0, 0, width, height))
	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			img.Set(x, y, c)
		}
	}
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("failed to create file: %v", err)
	}
	defer func() { _ = f.Close() }()
	if err := png.Encode(f, img); err != nil {
		t.Fatalf("failed to encode PNG: %v", err)
	}
}

// createTestPNGWithBlock creates a PNG with a colored block at the specified position.
func createTestPNGWithBlock(t *testing.T, path string, width, height int, bg, block color.Color, bx, by, bw, bh int) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatalf("failed to create dir: %v", err)
	}
	img := image.NewRGBA(image.Rect(0, 0, width, height))
	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			if x >= bx && x < bx+bw && y >= by && y < by+bh {
				img.Set(x, y, block)
			} else {
				img.Set(x, y, bg)
			}
		}
	}
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("failed to create file: %v", err)
	}
	defer func() { _ = f.Close() }()
	if err := png.Encode(f, img); err != nil {
		t.Fatalf("failed to encode PNG: %v", err)
	}
}

func TestCompare_IdenticalImages(t *testing.T) {
	dir := t.TempDir()
	baselinePath := filepath.Join(dir, "baseline.png")
	currentPath := filepath.Join(dir, "current.png")

	white := color.RGBA{R: 255, G: 255, B: 255, A: 255}
	createTestPNG(t, baselinePath, 100, 100, white)
	createTestPNG(t, currentPath, 100, 100, white)

	result, err := Compare(baselinePath, currentPath, 0.2)
	if err != nil {
		t.Fatalf("Compare failed: %v", err)
	}

	if result.Status != StatusUnchanged {
		t.Errorf("expected StatusUnchanged, got %s", result.Status)
	}
	if result.DiffPercent != 0.0 {
		t.Errorf("expected 0%% diff, got %.2f%%", result.DiffPercent)
	}
	if result.DiffPixels != 0 {
		t.Errorf("expected 0 diff pixels, got %d", result.DiffPixels)
	}
	if result.TotalPixels != 10000 {
		t.Errorf("expected 10000 total pixels, got %d", result.TotalPixels)
	}
}

func TestCompare_DifferentImages(t *testing.T) {
	dir := t.TempDir()
	baselinePath := filepath.Join(dir, "baseline.png")
	currentPath := filepath.Join(dir, "current.png")

	white := color.RGBA{R: 255, G: 255, B: 255, A: 255}
	red := color.RGBA{R: 255, G: 0, B: 0, A: 255}

	// Baseline: all white
	createTestPNG(t, baselinePath, 100, 100, white)
	// Current: white with a 10x10 red block (100 pixels different)
	createTestPNGWithBlock(t, currentPath, 100, 100, white, red, 0, 0, 10, 10)

	result, err := Compare(baselinePath, currentPath, 0.2)
	if err != nil {
		t.Fatalf("Compare failed: %v", err)
	}

	if result.Status != StatusChanged {
		t.Errorf("expected StatusChanged, got %s", result.Status)
	}
	if result.DiffPixels != 100 {
		t.Errorf("expected 100 diff pixels, got %d", result.DiffPixels)
	}
	if result.DiffPercent != 1.0 {
		t.Errorf("expected 1.0%% diff, got %.2f%%", result.DiffPercent)
	}
	if result.DiffImage == nil {
		t.Error("expected non-nil DiffImage")
	}
}

func TestCompare_SubtleDifferenceBelowThreshold(t *testing.T) {
	dir := t.TempDir()
	baselinePath := filepath.Join(dir, "baseline.png")
	currentPath := filepath.Join(dir, "current.png")

	// Two very similar colors -- difference of 10 on one channel
	c1 := color.RGBA{R: 200, G: 200, B: 200, A: 255}
	c2 := color.RGBA{R: 210, G: 200, B: 200, A: 255}

	createTestPNG(t, baselinePath, 10, 10, c1)
	createTestPNG(t, currentPath, 10, 10, c2)

	// Threshold 0.2 = 51 pixel value difference. 10 < 51, so should be unchanged.
	result, err := Compare(baselinePath, currentPath, 0.2)
	if err != nil {
		t.Fatalf("Compare failed: %v", err)
	}

	if result.Status != StatusUnchanged {
		t.Errorf("expected StatusUnchanged (diff below threshold), got %s", result.Status)
	}
	if result.DiffPixels != 0 {
		t.Errorf("expected 0 diff pixels (below threshold), got %d", result.DiffPixels)
	}
}

func TestCompare_DifferentSizes(t *testing.T) {
	dir := t.TempDir()
	baselinePath := filepath.Join(dir, "baseline.png")
	currentPath := filepath.Join(dir, "current.png")

	white := color.RGBA{R: 255, G: 255, B: 255, A: 255}
	createTestPNG(t, baselinePath, 100, 100, white)
	createTestPNG(t, currentPath, 100, 120, white) // Taller

	result, err := Compare(baselinePath, currentPath, 0.2)
	if err != nil {
		t.Fatalf("Compare failed: %v", err)
	}

	// The extra 20 rows (2000 pixels) should be "different" (white vs transparent/zero)
	if result.Status != StatusChanged {
		t.Errorf("expected StatusChanged for different sizes, got %s", result.Status)
	}
	if result.TotalPixels != 12000 { // 100*120
		t.Errorf("expected 12000 total pixels, got %d", result.TotalPixels)
	}
}

// A changed screenshot shows its diff percentage and the diff overlay.
func TestGenerateReport_rendersAChangedScreenshot(t *testing.T) {
	dir := t.TempDir()
	baselineDir := filepath.Join(dir, "baseline")
	currentDir := filepath.Join(dir, "current")

	white := color.RGBA{R: 255, G: 255, B: 255, A: 255}
	red := color.RGBA{R: 255, G: 0, B: 0, A: 255}

	createTestPNG(t, filepath.Join(baselineDir, "page.png"), 50, 50, white)
	createTestPNG(t, filepath.Join(currentDir, "page.png"), 50, 50, red)

	results, err := CompareDirectories(baselineDir, currentDir, 0.2)
	if err != nil {
		t.Fatalf("CompareDirectories failed: %v", err)
	}

	outputPath := filepath.Join(dir, "report", "index.html")
	if err := GenerateReport(results, outputPath); err != nil {
		t.Fatalf("GenerateReport failed: %v", err)
	}

	report := readFile(t, outputPath)
	for _, want := range []string{
		"1 Changed</div>",
		"100.00% changed",
		`alt="Diff overlay"`,
	} {
		if !strings.Contains(report, want) {
			t.Errorf("report missing %q", want)
		}
	}
	if strings.Contains(report, "No visual changes detected") {
		t.Error("report claims no changes")
	}
}
