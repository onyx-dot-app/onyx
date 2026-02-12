package imgdiff

import (
	"image"
	"image/color"
	"image/png"
	"os"
	"path/filepath"
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

func TestCompareDirectories(t *testing.T) {
	baselineDir := filepath.Join(t.TempDir(), "baseline")
	currentDir := filepath.Join(t.TempDir(), "current")

	white := color.RGBA{R: 255, G: 255, B: 255, A: 255}
	red := color.RGBA{R: 255, G: 0, B: 0, A: 255}
	blue := color.RGBA{R: 0, G: 0, B: 255, A: 255}

	// shared-unchanged.png: identical in both
	createTestPNG(t, filepath.Join(baselineDir, "shared-unchanged.png"), 10, 10, white)
	createTestPNG(t, filepath.Join(currentDir, "shared-unchanged.png"), 10, 10, white)

	// shared-changed.png: different in both
	createTestPNG(t, filepath.Join(baselineDir, "shared-changed.png"), 10, 10, white)
	createTestPNG(t, filepath.Join(currentDir, "shared-changed.png"), 10, 10, red)

	// removed.png: only in baseline
	createTestPNG(t, filepath.Join(baselineDir, "removed.png"), 10, 10, white)

	// added.png: only in current
	createTestPNG(t, filepath.Join(currentDir, "added.png"), 10, 10, blue)

	results, err := CompareDirectories(baselineDir, currentDir, 0.2)
	if err != nil {
		t.Fatalf("CompareDirectories failed: %v", err)
	}

	if len(results) != 4 {
		t.Fatalf("expected 4 results, got %d", len(results))
	}

	// Results should be sorted: changed first, then added, removed, unchanged
	statusCounts := map[Status]int{}
	for _, r := range results {
		statusCounts[r.Status]++
	}

	if statusCounts[StatusChanged] != 1 {
		t.Errorf("expected 1 changed, got %d", statusCounts[StatusChanged])
	}
	if statusCounts[StatusAdded] != 1 {
		t.Errorf("expected 1 added, got %d", statusCounts[StatusAdded])
	}
	if statusCounts[StatusRemoved] != 1 {
		t.Errorf("expected 1 removed, got %d", statusCounts[StatusRemoved])
	}
	if statusCounts[StatusUnchanged] != 1 {
		t.Errorf("expected 1 unchanged, got %d", statusCounts[StatusUnchanged])
	}

	// First result should be the changed one (sort order)
	if results[0].Status != StatusChanged {
		t.Errorf("expected first result to be changed, got %s", results[0].Status)
	}
}

func TestCompareDirectories_EmptyBaseline(t *testing.T) {
	baselineDir := filepath.Join(t.TempDir(), "baseline")
	currentDir := filepath.Join(t.TempDir(), "current")

	if err := os.MkdirAll(baselineDir, 0755); err != nil {
		t.Fatal(err)
	}

	white := color.RGBA{R: 255, G: 255, B: 255, A: 255}
	createTestPNG(t, filepath.Join(currentDir, "new.png"), 10, 10, white)

	results, err := CompareDirectories(baselineDir, currentDir, 0.2)
	if err != nil {
		t.Fatalf("CompareDirectories failed: %v", err)
	}

	if len(results) != 1 {
		t.Fatalf("expected 1 result, got %d", len(results))
	}
	if results[0].Status != StatusAdded {
		t.Errorf("expected StatusAdded, got %s", results[0].Status)
	}
}

func TestGenerateReport(t *testing.T) {
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

	// Verify the file was created and has content
	info, err := os.Stat(outputPath)
	if err != nil {
		t.Fatalf("report file not found: %v", err)
	}
	if info.Size() == 0 {
		t.Error("report file is empty")
	}

	// Verify it contains expected HTML elements
	content, err := os.ReadFile(outputPath)
	if err != nil {
		t.Fatalf("failed to read report: %v", err)
	}

	contentStr := string(content)
	for _, expected := range []string{
		"Visual Regression Report",
		"data:image/png;base64,",
		"page.png",
		"changed",
	} {
		if !contains(contentStr, expected) {
			t.Errorf("report missing expected content: %q", expected)
		}
	}
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && searchString(s, substr)
}

func searchString(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
