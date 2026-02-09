package cmd

import (
	"encoding/json"
	"fmt"
	"html/template"
	"image"
	"image/png"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// PlaywrightDiffOptions holds options for the playwright-diff command
type PlaywrightDiffOptions struct {
	RunID  string
	Tag    string
	Dir    string
	Output string
}

// NewPlaywrightDiffCommand creates a new playwright-diff command
func NewPlaywrightDiffCommand() *cobra.Command {
	opts := &PlaywrightDiffOptions{}

	cmd := &cobra.Command{
		Use:   "playwright-diff",
		Short: "Compare Playwright screenshots between runs",
		Long: `Compare Playwright screenshots between different CI runs, releases, or local directories.

This command downloads screenshot artifacts from GitHub Actions and generates
an HTML report showing visual differences.

Requires the GitHub CLI (gh) for downloading CI artifacts.

Examples:
  # Compare local screenshots against a CI run
  ods playwright-diff --run-id 12345678

  # Compare local screenshots against a tagged release
  ods playwright-diff --tag v2.10.4

  # Compare two local directories
  ods playwright-diff --dir /path/to/baseline/screenshots

  # Specify output location for the diff report
  ods playwright-diff --run-id 12345678 --output /tmp/diff-report.html`,
		Run: func(cmd *cobra.Command, args []string) {
			runPlaywrightDiff(opts)
		},
	}

	cmd.Flags().StringVar(&opts.RunID, "run-id", "", "GitHub Actions run ID to compare against")
	cmd.Flags().StringVar(&opts.Tag, "tag", "", "Git tag (release version) to compare against")
	cmd.Flags().StringVar(&opts.Dir, "dir", "", "Local directory to compare against")
	cmd.Flags().StringVar(&opts.Output, "output", "", "Output path for the HTML diff report (default: playwright-diff-report.html)")

	return cmd
}

// screenshotPair represents a pair of screenshots for comparison
type screenshotPair struct {
	Name         string
	BaselinePath string
	CurrentPath  string
	Status       string // "added", "removed", "changed", "unchanged"
	DiffPercent  float64
}

func runPlaywrightDiff(opts *PlaywrightDiffOptions) {
	// Validate that exactly one source is specified
	sources := 0
	if opts.RunID != "" {
		sources++
	}
	if opts.Tag != "" {
		sources++
	}
	if opts.Dir != "" {
		sources++
	}
	if sources == 0 {
		log.Fatal("Specify one of --run-id, --tag, or --dir to provide baseline screenshots")
	}
	if sources > 1 {
		log.Fatal("Specify only one of --run-id, --tag, or --dir")
	}

	// Find local screenshots
	gitRoot, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}
	localDir := filepath.Join(gitRoot, "web", "screenshots")

	if _, err := os.Stat(localDir); os.IsNotExist(err) {
		log.Fatalf("Local screenshots directory not found: %s\nRun Playwright tests first to generate screenshots.", localDir)
	}

	// Get baseline directory
	var baselineDir string
	var cleanup func()

	switch {
	case opts.RunID != "":
		baselineDir, cleanup = downloadFromRunID(opts.RunID)
	case opts.Tag != "":
		baselineDir, cleanup = downloadFromTag(opts.Tag)
	case opts.Dir != "":
		baselineDir = opts.Dir
	}

	if cleanup != nil {
		defer cleanup()
	}

	if _, err := os.Stat(baselineDir); os.IsNotExist(err) {
		log.Fatalf("Baseline directory not found: %s", baselineDir)
	}

	// Compare screenshots
	pairs := compareDirectories(baselineDir, localDir)

	// Print summary
	printSummary(pairs)

	// Generate HTML report
	outputPath := opts.Output
	if outputPath == "" {
		outputPath = filepath.Join(gitRoot, "playwright-diff-report.html")
	}
	generateHTMLReport(pairs, baselineDir, localDir, outputPath)

	log.Infof("Diff report generated: %s", outputPath)
}

// downloadFromRunID downloads screenshot artifacts from a GitHub Actions run
func downloadFromRunID(runID string) (string, func()) {
	git.CheckGitHubCLI()

	tmpDir, err := os.MkdirTemp("", "playwright-diff-*")
	if err != nil {
		log.Fatalf("Failed to create temp directory: %v", err)
	}
	cleanup := func() { _ = os.RemoveAll(tmpDir) }

	log.Infof("Downloading screenshots from CI run %s ...", runID)

	// Try both admin and exclusive project artifacts
	for _, project := range []string{"admin", "exclusive"} {
		artifactName := fmt.Sprintf("playwright-screenshots-%s-%s", project, runID)
		cmd := exec.Command("gh", "run", "download", runID,
			"--name", artifactName,
			"--dir", filepath.Join(tmpDir, project))

		output, err := cmd.CombinedOutput()
		if err != nil {
			log.Debugf("No artifact %s found (this is normal if project wasn't run): %s", artifactName, string(output))
			continue
		}
		log.Infof("Downloaded %s screenshots", project)
	}

	return tmpDir, cleanup
}

// downloadFromTag downloads screenshots from the CI run associated with a git tag
func downloadFromTag(tag string) (string, func()) {
	git.CheckGitHubCLI()

	log.Infof("Finding CI run for tag %s ...", tag)

	// Get the run ID for this tag
	cmd := exec.Command("gh", "run", "list",
		"--branch", tag,
		"--workflow", "pr-playwright-tests.yml",
		"--limit", "1",
		"--json", "databaseId",
	)

	output, err := cmd.Output()
	if err != nil {
		log.Fatalf("Failed to find CI run for tag %s: %v", tag, err)
	}

	// Parse the run ID from JSON output
	type runInfo struct {
		DatabaseID int `json:"databaseId"`
	}
	var runs []runInfo

	// Simple JSON parsing
	outputStr := strings.TrimSpace(string(output))
	if outputStr == "[]" || outputStr == "" {
		log.Fatalf("No CI runs found for tag %s", tag)
	}

	if err := json.Unmarshal([]byte(outputStr), &runs); err != nil {
		log.Fatalf("Failed to parse CI run info: %v", err)
	}

	if len(runs) == 0 {
		log.Fatalf("No CI runs found for tag %s", tag)
	}

	runID := fmt.Sprintf("%d", runs[0].DatabaseID)
	log.Infof("Found CI run %s for tag %s", runID, tag)

	return downloadFromRunID(runID)
}

// compareDirectories compares two screenshot directories and returns pairs
func compareDirectories(baselineDir, currentDir string) []screenshotPair {
	baselineFiles := collectPNGs(baselineDir)
	currentFiles := collectPNGs(currentDir)

	// Create maps for lookup
	baselineMap := make(map[string]string)
	for _, f := range baselineFiles {
		rel, _ := filepath.Rel(baselineDir, f)
		baselineMap[rel] = f
	}

	currentMap := make(map[string]string)
	for _, f := range currentFiles {
		rel, _ := filepath.Rel(currentDir, f)
		currentMap[rel] = f
	}

	// Collect all unique names
	allNames := make(map[string]bool)
	for name := range baselineMap {
		allNames[name] = true
	}
	for name := range currentMap {
		allNames[name] = true
	}

	// Build pairs
	var pairs []screenshotPair
	for name := range allNames {
		pair := screenshotPair{Name: name}

		baselinePath, hasBaseline := baselineMap[name]
		currentPath, hasCurrent := currentMap[name]

		switch {
		case hasBaseline && hasCurrent:
			pair.BaselinePath = baselinePath
			pair.CurrentPath = currentPath
			pair.DiffPercent = computeDiffPercent(baselinePath, currentPath)
			if pair.DiffPercent == 0 {
				pair.Status = "unchanged"
			} else {
				pair.Status = "changed"
			}
		case hasBaseline && !hasCurrent:
			pair.BaselinePath = baselinePath
			pair.Status = "removed"
		case !hasBaseline && hasCurrent:
			pair.CurrentPath = currentPath
			pair.Status = "added"
		}

		pairs = append(pairs, pair)
	}

	// Sort: changed first, then added, removed, unchanged
	statusOrder := map[string]int{"changed": 0, "added": 1, "removed": 2, "unchanged": 3}
	sort.Slice(pairs, func(i, j int) bool {
		if statusOrder[pairs[i].Status] != statusOrder[pairs[j].Status] {
			return statusOrder[pairs[i].Status] < statusOrder[pairs[j].Status]
		}
		return pairs[i].Name < pairs[j].Name
	})

	return pairs
}

// collectPNGs recursively collects all PNG files in a directory
func collectPNGs(dir string) []string {
	var files []string
	_ = filepath.Walk(dir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if !info.IsDir() && strings.HasSuffix(strings.ToLower(info.Name()), ".png") {
			files = append(files, path)
		}
		return nil
	})
	return files
}

// computeDiffPercent computes the percentage of pixels that differ between two images
func computeDiffPercent(path1, path2 string) float64 {
	img1, err := loadPNG(path1)
	if err != nil {
		log.Debugf("Failed to load %s: %v", path1, err)
		return 100.0
	}

	img2, err := loadPNG(path2)
	if err != nil {
		log.Debugf("Failed to load %s: %v", path2, err)
		return 100.0
	}

	bounds1 := img1.Bounds()
	bounds2 := img2.Bounds()

	// If dimensions differ, they're definitely different
	if bounds1.Dx() != bounds2.Dx() || bounds1.Dy() != bounds2.Dy() {
		return 100.0
	}

	totalPixels := bounds1.Dx() * bounds1.Dy()
	if totalPixels == 0 {
		return 0
	}

	diffPixels := 0
	for y := bounds1.Min.Y; y < bounds1.Max.Y; y++ {
		for x := bounds1.Min.X; x < bounds1.Max.X; x++ {
			r1, g1, b1, a1 := img1.At(x, y).RGBA()
			r2, g2, b2, a2 := img2.At(x, y).RGBA()
			if r1 != r2 || g1 != g2 || b1 != b2 || a1 != a2 {
				diffPixels++
			}
		}
	}

	return math.Round(float64(diffPixels)/float64(totalPixels)*10000) / 100 // 2 decimal places
}

// loadPNG loads a PNG image from disk
func loadPNG(path string) (image.Image, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer func() { _ = f.Close() }()

	img, err := png.Decode(f)
	if err != nil {
		return nil, err
	}

	return img, nil
}

// printSummary prints a terminal summary of the diff results
func printSummary(pairs []screenshotPair) {
	changed, added, removed, unchanged := 0, 0, 0, 0
	for _, p := range pairs {
		switch p.Status {
		case "changed":
			changed++
		case "added":
			added++
		case "removed":
			removed++
		case "unchanged":
			unchanged++
		}
	}

	log.Infof("Screenshot comparison: %d changed, %d added, %d removed, %d unchanged",
		changed, added, removed, unchanged)

	for _, p := range pairs {
		switch p.Status {
		case "changed":
			log.Infof("  CHANGED  %s (%.1f%% diff)", p.Name, p.DiffPercent)
		case "added":
			log.Infof("  ADDED    %s", p.Name)
		case "removed":
			log.Infof("  REMOVED  %s", p.Name)
		}
	}
}

// generateHTMLReport creates an HTML report showing side-by-side screenshot comparisons
func generateHTMLReport(pairs []screenshotPair, baselineDir, currentDir, outputPath string) {
	tmpl := template.Must(template.New("report").Parse(reportTemplate))

	f, err := os.Create(outputPath)
	if err != nil {
		log.Fatalf("Failed to create report file: %v", err)
	}
	defer func() { _ = f.Close() }()

	data := struct {
		Pairs       []screenshotPair
		BaselineDir string
		CurrentDir  string
	}{
		Pairs:       pairs,
		BaselineDir: baselineDir,
		CurrentDir:  currentDir,
	}

	if err := tmpl.Execute(f, data); err != nil {
		log.Fatalf("Failed to generate report: %v", err)
	}
}

const reportTemplate = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Playwright Screenshot Diff Report</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; padding: 24px; }
  h1 { margin-bottom: 8px; }
  .summary { margin-bottom: 24px; color: #666; }
  .pair { background: #fff; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 16px; overflow: hidden; }
  .pair-header { padding: 12px 16px; border-bottom: 1px solid #eee; display: flex; align-items: center; gap: 12px; }
  .pair-header h3 { flex: 1; font-size: 14px; font-weight: 500; }
  .badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; }
  .badge-changed { background: #fff3cd; color: #856404; }
  .badge-added { background: #d4edda; color: #155724; }
  .badge-removed { background: #f8d7da; color: #721c24; }
  .badge-unchanged { background: #e2e3e5; color: #383d41; }
  .diff-percent { font-size: 12px; color: #999; }
  .images { display: flex; gap: 0; }
  .images > div { flex: 1; padding: 12px; }
  .images > div:first-child { border-right: 1px solid #eee; }
  .images label { display: block; font-size: 11px; color: #999; margin-bottom: 4px; text-transform: uppercase; }
  .images img { max-width: 100%; border: 1px solid #eee; border-radius: 4px; }
  .no-image { color: #ccc; font-style: italic; padding: 40px; text-align: center; background: #fafafa; border-radius: 4px; }
</style>
</head>
<body>
<h1>Playwright Screenshot Diff</h1>
<p class="summary">Baseline: {{.BaselineDir}} &nbsp;|&nbsp; Current: {{.CurrentDir}}</p>

{{range .Pairs}}
<div class="pair">
  <div class="pair-header">
    <span class="badge badge-{{.Status}}">{{.Status}}</span>
    <h3>{{.Name}}</h3>
    {{if eq .Status "changed"}}<span class="diff-percent">{{printf "%.1f" .DiffPercent}}% pixels differ</span>{{end}}
  </div>
  <div class="images">
    <div>
      <label>Baseline</label>
      {{if .BaselinePath}}<img src="file://{{.BaselinePath}}" alt="Baseline">{{else}}<div class="no-image">No baseline</div>{{end}}
    </div>
    <div>
      <label>Current</label>
      {{if .CurrentPath}}<img src="file://{{.CurrentPath}}" alt="Current">{{else}}<div class="no-image">No current screenshot</div>{{end}}
    </div>
  </div>
</div>
{{end}}

</body>
</html>
`
