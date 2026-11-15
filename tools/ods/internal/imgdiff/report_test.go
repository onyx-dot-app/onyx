package imgdiff

import (
	"encoding/base64"
	"html"
	"image"
	"image/color"
	"image/png"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestGenerateReport_rendersAddedRemovedAndUnchanged(t *testing.T) {
	dir := t.TempDir()
	baselineDir := filepath.Join(dir, "baseline")
	currentDir := filepath.Join(dir, "current")
	white := color.RGBA{R: 255, G: 255, B: 255, A: 255}
	createTestPNG(t, filepath.Join(baselineDir, "same.png"), 4, 4, white)
	createTestPNG(t, filepath.Join(currentDir, "same.png"), 4, 4, white)
	createTestPNG(t, filepath.Join(baselineDir, "gone.png"), 4, 4, white)
	createTestPNG(t, filepath.Join(currentDir, "new.png"), 6, 6, white)

	results, err := CompareDirectories(baselineDir, currentDir, 0.2)
	if err != nil {
		t.Fatalf("CompareDirectories failed: %v", err)
	}
	outputPath := filepath.Join(dir, "report", "index.html")
	if err := GenerateReport(results, outputPath); err != nil {
		t.Fatalf("GenerateReport failed: %v", err)
	}

	// The template writes + in a data URI as an HTML entity; a browser reads it back.
	report := html.UnescapeString(readFile(t, outputPath))
	newPNG, err := os.ReadFile(filepath.Join(currentDir, "new.png"))
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		"3 screenshots compared",
		"1 Added",
		"1 Removed",
		"1 Unchanged",
		`<img src="data:image/png;base64,` + base64.StdEncoding.EncodeToString(newPNG) + `" alt="New screenshot">`,
		`alt="Removed screenshot"`,
		`<div class="unchanged-item">same.png</div>`,
		"1 unchanged screenshot (click to expand)",
	} {
		if !strings.Contains(report, want) {
			t.Errorf("report missing %q", want)
		}
	}
	for _, unwanted := range []string{"Changed</div>", "No visual changes detected"} {
		if strings.Contains(report, unwanted) {
			t.Errorf("report unexpectedly contains %q", unwanted)
		}
	}
}

func TestGenerateReport_saysSoWhenNothingChanged(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "a.png")
	createTestPNG(t, path, 2, 2, color.Black)
	results := []Result{
		{Name: "a.png", Status: StatusUnchanged, BaselinePath: path, CurrentPath: path},
		{Name: "b.png", Status: StatusUnchanged, BaselinePath: path, CurrentPath: path},
	}
	outputPath := filepath.Join(dir, "index.html")

	if err := GenerateReport(results, outputPath); err != nil {
		t.Fatalf("GenerateReport failed: %v", err)
	}

	report := readFile(t, outputPath)
	for _, want := range []string{
		"No visual changes detected",
		"All 2 screenshots match their baselines.",
		"2 unchanged screenshots (click to expand)",
	} {
		if !strings.Contains(report, want) {
			t.Errorf("report missing %q", want)
		}
	}
}

func TestGenerateReport_reportsFailures(t *testing.T) {
	dir := t.TempDir()
	valid := filepath.Join(dir, "valid.png")
	createTestPNG(t, valid, 2, 2, color.White)
	missing := filepath.Join(dir, "missing.png")
	file := filepath.Join(dir, "file")
	if err := os.WriteFile(file, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	report := filepath.Join(dir, "index.html")

	tests := []struct {
		name       string
		results    []Result
		outputPath string
		want       string
	}{
		{"uncreatable directory", nil, filepath.Join(file, "index.html"), "failed to create output directory"},
		{"unreadable baseline", []Result{{Name: "a.png", Status: StatusRemoved, BaselinePath: missing}}, report, "failed to encode baseline a.png"},
		{"unreadable current", []Result{{Name: "a.png", Status: StatusAdded, CurrentPath: missing}}, report, "failed to encode current a.png"},
		{
			"unencodable diff",
			[]Result{{Name: "a.png", Status: StatusChanged, BaselinePath: valid, CurrentPath: valid, DiffImage: image.NewRGBA(image.Rect(0, 0, 0, 0))}},
			report,
			"failed to encode diff a.png",
		},
		{"output is a directory", nil, dir, "failed to create output file"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := GenerateReport(tt.results, tt.outputPath)
			if err == nil || !strings.HasPrefix(err.Error(), tt.want) {
				t.Fatalf("expected %q, got %v", tt.want, err)
			}
		})
	}
}

func TestSaveDiffImage_writesAPNG(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 3, 2))
	magenta := color.RGBA{R: 255, B: 255, A: 255}
	img.Set(2, 1, magenta)
	path := filepath.Join(t.TempDir(), "diffs", "page.png")

	if err := SaveDiffImage(img, path); err != nil {
		t.Fatalf("SaveDiffImage failed: %v", err)
	}

	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	decoded, err := png.Decode(f)
	if err != nil {
		t.Fatalf("saved file is not a PNG: %v", err)
	}
	if decoded.Bounds() != img.Bounds() {
		t.Fatalf("expected bounds %v, got %v", img.Bounds(), decoded.Bounds())
	}
	if got := color.RGBAModel.Convert(decoded.At(2, 1)); got != magenta {
		t.Fatalf("expected %v at (2,1), got %v", magenta, got)
	}
}

func TestSaveDiffImage_reportsFailures(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "file")
	if err := os.WriteFile(file, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	valid := image.NewRGBA(image.Rect(0, 0, 1, 1))

	tests := []struct {
		name string
		img  image.Image
		path string
		want string
	}{
		{"parent is a file", valid, filepath.Join(file, "diff.png"), "failed to create directory"},
		{"path is a directory", valid, dir, "failed to create file"},
		{"empty image", image.NewRGBA(image.Rect(0, 0, 0, 0)), filepath.Join(dir, "empty.png"), "failed to encode PNG"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := SaveDiffImage(tt.img, tt.path)
			if err == nil || !strings.HasPrefix(err.Error(), tt.want) {
				t.Fatalf("expected %q, got %v", tt.want, err)
			}
		})
	}
}

func readFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}
