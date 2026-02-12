package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/imgdiff"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/s3"
)

const (
	// DefaultS3Bucket is the default S3 bucket for Playwright visual regression artifacts.
	DefaultS3Bucket = "onyx-playwright-artifacts"

	// DefaultScreenshotDir is the default local directory for captured screenshots,
	// relative to the repository root.
	DefaultScreenshotDir = "web/output/screenshots"

	// DefaultOutputDir is the default base directory for visual diff output,
	// relative to the repository root.
	DefaultOutputDir = "web/output/visual-diff"
)

// getS3Bucket returns the S3 bucket name, preferring the PLAYWRIGHT_S3_BUCKET
// environment variable over the compiled-in default.
func getS3Bucket() string {
	if bucket := os.Getenv("PLAYWRIGHT_S3_BUCKET"); bucket != "" {
		return bucket
	}
	return DefaultS3Bucket
}

// PlaywrightDiffCompareOptions holds options for the compare subcommand.
type PlaywrightDiffCompareOptions struct {
	Project      string
	Baseline     string
	Current      string
	Output       string
	Threshold    float64
	MaxDiffRatio float64
}

// PlaywrightDiffUploadOptions holds options for the upload-baselines subcommand.
type PlaywrightDiffUploadOptions struct {
	Project string
	Dir     string
	Dest    string
	Delete  bool
}

// NewPlaywrightDiffCommand creates the playwright-diff command with subcommands.
func NewPlaywrightDiffCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "playwright-diff",
		Short: "Visual regression testing for Playwright screenshots",
		Long: `Compare Playwright screenshots against baselines and generate visual diff reports.

Supports comparing local directories and downloading baselines from S3.
The generated HTML report is self-contained (images base64-inlined) and can
be opened locally or hosted on S3.

The --project flag provides sensible defaults so you don't need to specify
every path. For example:

  # Compare the "admin" project against S3 baselines (uses all defaults)
  ods playwright-diff compare --project admin

  # Upload new baselines for the "admin" project
  ods playwright-diff upload-baselines --project admin

You can override any default with explicit flags:

  # Compare with custom paths
  ods playwright-diff compare --baseline ./my-baselines --current ./my-screenshots`,
		Run: func(cmd *cobra.Command, args []string) {
			_ = cmd.Help()
		},
	}

	cmd.AddCommand(newCompareCommand())
	cmd.AddCommand(newUploadBaselinesCommand())

	return cmd
}

func newCompareCommand() *cobra.Command {
	opts := &PlaywrightDiffCompareOptions{}

	cmd := &cobra.Command{
		Use:   "compare",
		Short: "Compare screenshots against baselines and generate a diff report",
		Long: `Compare current screenshots against baseline screenshots and produce
a self-contained HTML visual diff report with a JSON summary.

When --project is specified, the following defaults are applied:
  --baseline  → s3://<bucket>/baselines/<project>/
  --current   → web/output/screenshots/
  --output    → web/output/visual-diff/<project>/index.html

The bucket defaults to "onyx-playwright-artifacts" and can be overridden
with the PLAYWRIGHT_S3_BUCKET environment variable.

A summary.json file is always written next to the HTML report. If there
are no visual differences, the HTML report is skipped.

Examples:

  # Use project defaults (recommended)
  ods playwright-diff compare --project admin

  # Override specific flags
  ods playwright-diff compare --project admin --current ./custom-dir/

  # Fully manual (no project flag)
  ods playwright-diff compare \
    --baseline s3://my-bucket/baselines/admin/ \
    --current ./web/output/screenshots/ \
    --output ./web/output/visual-diff/admin/index.html`,
		Run: func(cmd *cobra.Command, args []string) {
			runCompare(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Project, "project", "", "Project name (e.g. admin); sets sensible defaults for baseline, current, and output")
	cmd.Flags().StringVar(&opts.Baseline, "baseline", "", "Baseline directory or S3 URL (s3://...)")
	cmd.Flags().StringVar(&opts.Current, "current", "", "Current screenshots directory")
	cmd.Flags().StringVar(&opts.Output, "output", "", "Output path for the HTML report")
	cmd.Flags().Float64Var(&opts.Threshold, "threshold", 0.2, "Per-channel pixel difference threshold (0.0-1.0)")
	cmd.Flags().Float64Var(&opts.MaxDiffRatio, "max-diff-ratio", 0.01, "Max diff pixel ratio before marking as changed (informational)")

	return cmd
}

func newUploadBaselinesCommand() *cobra.Command {
	opts := &PlaywrightDiffUploadOptions{}

	cmd := &cobra.Command{
		Use:   "upload-baselines",
		Short: "Upload screenshots to S3 as new baselines",
		Long: `Upload a local directory of screenshots to S3 to serve as the new
baseline for future comparisons. Typically run after tests pass on the
main branch.

When --project is specified, the following defaults are applied:
  --dir   → web/output/screenshots/
  --dest  → s3://<bucket>/baselines/<project>/

Examples:

  # Use project defaults (recommended)
  ods playwright-diff upload-baselines --project admin

  # With delete (remove old baselines not in current set)
  ods playwright-diff upload-baselines --project admin --delete

  # Fully manual
  ods playwright-diff upload-baselines \
    --dir ./web/output/screenshots/ \
    --dest s3://onyx-playwright-artifacts/baselines/admin/`,
		Run: func(cmd *cobra.Command, args []string) {
			runUploadBaselines(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Project, "project", "", "Project name (e.g. admin); sets sensible defaults for dir and dest")
	cmd.Flags().StringVar(&opts.Dir, "dir", "", "Local directory containing screenshots to upload")
	cmd.Flags().StringVar(&opts.Dest, "dest", "", "S3 destination URL (s3://...)")
	cmd.Flags().BoolVar(&opts.Delete, "delete", false, "Delete S3 files not present locally")

	return cmd
}

// resolveCompareDefaults fills in missing flags from the --project default when set.
func resolveCompareDefaults(opts *PlaywrightDiffCompareOptions) {
	bucket := getS3Bucket()

	if opts.Project != "" {
		if opts.Baseline == "" {
			opts.Baseline = fmt.Sprintf("s3://%s/baselines/%s/", bucket, opts.Project)
		}
		if opts.Current == "" {
			opts.Current = DefaultScreenshotDir
		}
		if opts.Output == "" {
			opts.Output = filepath.Join(DefaultOutputDir, opts.Project, "index.html")
		}
	}

	// Fall back for output even without --project
	if opts.Output == "" {
		opts.Output = "visual-diff/index.html"
	}
}

// resolveUploadDefaults fills in missing flags from the --project default when set.
func resolveUploadDefaults(opts *PlaywrightDiffUploadOptions) {
	bucket := getS3Bucket()

	if opts.Project != "" {
		if opts.Dir == "" {
			opts.Dir = DefaultScreenshotDir
		}
		if opts.Dest == "" {
			opts.Dest = fmt.Sprintf("s3://%s/baselines/%s/", bucket, opts.Project)
		}
	}
}

func runCompare(opts *PlaywrightDiffCompareOptions) {
	resolveCompareDefaults(opts)

	// Validate required fields
	if opts.Baseline == "" {
		log.Fatal("--baseline is required (or use --project to set defaults)")
	}
	if opts.Current == "" {
		log.Fatal("--current is required (or use --project to set defaults)")
	}

	// Determine the project name for the summary (use flag or derive from path)
	project := opts.Project
	if project == "" {
		project = "default"
	}

	baselineDir := opts.Baseline

	// If baseline is an S3 URL, download to a temp directory
	if strings.HasPrefix(opts.Baseline, "s3://") {
		tmpDir, err := os.MkdirTemp("", "playwright-baselines-*")
		if err != nil {
			log.Fatalf("Failed to create temp directory: %v", err)
		}
		defer func() { _ = os.RemoveAll(tmpDir) }()

		if err := s3.SyncDown(opts.Baseline, tmpDir); err != nil {
			log.Fatalf("Failed to download baselines from S3: %v", err)
		}
		baselineDir = tmpDir
	}

	// Verify directories exist
	if _, err := os.Stat(baselineDir); os.IsNotExist(err) {
		log.Warnf("Baseline directory does not exist: %s", baselineDir)
		log.Warn("This may be the first run -- no baselines to compare against.")
		// Create an empty dir so CompareDirectories works (all files will be "added")
		if err := os.MkdirAll(baselineDir, 0755); err != nil {
			log.Fatalf("Failed to create baseline directory: %v", err)
		}
	}

	// Resolve the output path
	outputPath := opts.Output
	if !filepath.IsAbs(outputPath) {
		cwd, err := os.Getwd()
		if err != nil {
			log.Fatalf("Failed to get working directory: %v", err)
		}
		outputPath = filepath.Join(cwd, outputPath)
	}
	summaryPath := filepath.Join(filepath.Dir(outputPath), "summary.json")

	// If the current screenshots directory doesn't exist, write an empty summary and exit
	if _, err := os.Stat(opts.Current); os.IsNotExist(err) {
		log.Warnf("Current screenshots directory does not exist: %s", opts.Current)
		log.Warn("No screenshots captured for this project — writing empty summary.")

		summary := imgdiff.Summary{Project: project}
		if err := imgdiff.WriteSummary(summary, summaryPath); err != nil {
			log.Fatalf("Failed to write summary: %v", err)
		}
		log.Infof("Summary written to: %s", summaryPath)
		return
	}

	log.Infof("Comparing screenshots...")
	log.Infof("  Baseline: %s", baselineDir)
	log.Infof("  Current:  %s", opts.Current)
	log.Infof("  Threshold: %.2f", opts.Threshold)

	results, err := imgdiff.CompareDirectories(baselineDir, opts.Current, opts.Threshold)
	if err != nil {
		log.Fatalf("Comparison failed: %v", err)
	}

	// Print terminal summary
	printSummary(results)

	// Build and write JSON summary (always)
	summary := imgdiff.BuildSummary(project, results)
	if err := imgdiff.WriteSummary(summary, summaryPath); err != nil {
		log.Fatalf("Failed to write summary: %v", err)
	}
	log.Infof("Summary written to: %s", summaryPath)

	// Generate HTML report only if there are differences
	if summary.HasDifferences {
		log.Infof("Generating report: %s", outputPath)
		if err := imgdiff.GenerateReport(results, outputPath); err != nil {
			log.Fatalf("Failed to generate report: %v", err)
		}
		log.Infof("Report generated successfully: %s", outputPath)
	} else {
		log.Infof("No visual differences detected — skipping report generation.")
	}
}

func runUploadBaselines(opts *PlaywrightDiffUploadOptions) {
	resolveUploadDefaults(opts)

	// Validate required fields
	if opts.Dir == "" {
		log.Fatal("--dir is required (or use --project to set defaults)")
	}
	if opts.Dest == "" {
		log.Fatal("--dest is required (or use --project to set defaults)")
	}

	if _, err := os.Stat(opts.Dir); os.IsNotExist(err) {
		log.Fatalf("Screenshots directory does not exist: %s", opts.Dir)
	}

	if !strings.HasPrefix(opts.Dest, "s3://") {
		log.Fatalf("Destination must be an S3 URL (s3://...): %s", opts.Dest)
	}

	log.Infof("Uploading baselines...")
	log.Infof("  Source: %s", opts.Dir)
	log.Infof("  Dest:   %s", opts.Dest)

	if err := s3.SyncUp(opts.Dir, opts.Dest, opts.Delete); err != nil {
		log.Fatalf("Failed to upload baselines: %v", err)
	}

	log.Info("Baselines uploaded successfully.")
}

func printSummary(results []imgdiff.Result) {
	changed, added, removed, unchanged := 0, 0, 0, 0
	for _, r := range results {
		switch r.Status {
		case imgdiff.StatusChanged:
			changed++
		case imgdiff.StatusAdded:
			added++
		case imgdiff.StatusRemoved:
			removed++
		case imgdiff.StatusUnchanged:
			unchanged++
		}
	}

	fmt.Println()
	fmt.Println("╔══════════════════════════════════════════════╗")
	fmt.Println("║          Visual Regression Summary           ║")
	fmt.Println("╠══════════════════════════════════════════════╣")
	fmt.Printf("║  Changed:   %-32d ║\n", changed)
	fmt.Printf("║  Added:     %-32d ║\n", added)
	fmt.Printf("║  Removed:   %-32d ║\n", removed)
	fmt.Printf("║  Unchanged: %-32d ║\n", unchanged)
	fmt.Printf("║  Total:     %-32d ║\n", len(results))
	fmt.Println("╚══════════════════════════════════════════════╝")
	fmt.Println()

	if changed > 0 || added > 0 || removed > 0 {
		for _, r := range results {
			switch r.Status {
			case imgdiff.StatusChanged:
				fmt.Printf("  ⚠ CHANGED  %s (%.2f%% diff)\n", r.Name, r.DiffPercent)
			case imgdiff.StatusAdded:
				fmt.Printf("  ✚ ADDED    %s\n", r.Name)
			case imgdiff.StatusRemoved:
				fmt.Printf("  ✖ REMOVED  %s\n", r.Name)
			}
		}
		fmt.Println()
	}
}
