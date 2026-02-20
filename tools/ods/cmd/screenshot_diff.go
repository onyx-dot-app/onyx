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

	// DefaultOutputDir is the default base directory for screenshot diff output,
	// relative to the repository root.
	DefaultOutputDir = "web/output/screenshot-diff"

	// DefaultRev is the default revision used when --rev is not specified.
	DefaultRev = "main"
)

// getS3Bucket returns the S3 bucket name, preferring the PLAYWRIGHT_S3_BUCKET
// environment variable over the compiled-in default.
func getS3Bucket() string {
	if bucket := os.Getenv("PLAYWRIGHT_S3_BUCKET"); bucket != "" {
		return bucket
	}
	return DefaultS3Bucket
}

// sanitizeRev normalises a git ref for use as an S3 path segment.
// Slashes are replaced with dashes (e.g. "release/2.5" → "release-2.5").
func sanitizeRev(rev string) string {
	return strings.ReplaceAll(rev, "/", "-")
}

// ScreenshotDiffCompareOptions holds options for the compare subcommand.
type ScreenshotDiffCompareOptions struct {
	Project      string
	Rev          string // revision whose baseline to compare against (default: "main")
	FromRev      string // cross-revision mode: source (older) revision
	ToRev        string // cross-revision mode: target (newer) revision
	Baseline     string
	Current      string
	Output       string
	Threshold    float64
	MaxDiffRatio float64
}

// ScreenshotDiffUploadOptions holds options for the upload-baselines subcommand.
type ScreenshotDiffUploadOptions struct {
	Project string
	Rev     string // revision to store the baseline under (default: "main")
	Dir     string
	Dest    string
	Delete  bool
}

// NewScreenshotDiffCommand creates the screenshot-diff command with subcommands.
func NewScreenshotDiffCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "screenshot-diff",
		Short: "Visual regression testing for Playwright screenshots",
		Long: `Compare Playwright screenshots against baselines and generate visual diff reports.

Supports comparing local directories and downloading baselines from S3.
The generated HTML report is self-contained (images base64-inlined) and can
be opened locally or hosted on S3.

Baselines are stored per-project and per-revision in S3:

  s3://<bucket>/baselines/<project>/<rev>/

The --project flag provides sensible defaults so you don't need to specify
every path. For example:

  # Compare local screenshots against the "main" baseline (default)
  ods screenshot-diff compare --project admin

  # Compare against a release branch baseline
  ods screenshot-diff compare --project admin --rev release/2.5

  # Compare two revisions directly (no local screenshots needed)
  ods screenshot-diff compare --project admin --from-rev v1.0.0 --to-rev v2.0.0

  # Upload new baselines for the "admin" project on main
  ods screenshot-diff upload-baselines --project admin

  # Upload baselines for a release branch
  ods screenshot-diff upload-baselines --project admin --rev release/2.5

You can override any default with explicit flags:

  ods screenshot-diff compare --baseline ./my-baselines --current ./my-screenshots`,
		Run: func(cmd *cobra.Command, args []string) {
			_ = cmd.Help()
		},
	}

	cmd.AddCommand(newCompareCommand())
	cmd.AddCommand(newUploadBaselinesCommand())

	return cmd
}

func newCompareCommand() *cobra.Command {
	opts := &ScreenshotDiffCompareOptions{}

	cmd := &cobra.Command{
		Use:   "compare",
		Short: "Compare screenshots against baselines and generate a diff report",
		Long: `Compare current screenshots against baseline screenshots and produce
a self-contained HTML visual diff report with a JSON summary.

Baselines are stored per-revision in S3:

  s3://<bucket>/baselines/<project>/<rev>/

When --project is specified, the following defaults are applied:
  --baseline  → s3://<bucket>/baselines/<project>/<rev>/
  --current   → web/output/screenshots/
  --output    → web/output/screenshot-diff/<project>/index.html
  --rev       → main

The bucket defaults to "onyx-playwright-artifacts" and can be overridden
with the PLAYWRIGHT_S3_BUCKET environment variable.

A summary.json file is always written next to the HTML report. If there
are no visual differences, the HTML report is skipped.

CROSS-REVISION MODE:

Use --from-rev and --to-rev to compare two stored revisions directly.
Both sides are downloaded from S3 — no local screenshots are needed.

  ods screenshot-diff compare --project admin --from-rev v1.0.0 --to-rev v2.0.0

Examples:

  # Compare local screenshots against main (default)
  ods screenshot-diff compare --project admin

  # Compare against a specific revision
  ods screenshot-diff compare --project admin --rev release/2.5

  # Compare two revisions
  ods screenshot-diff compare --project admin --from-rev v1.0.0 --to-rev v2.0.0

  # Override specific flags
  ods screenshot-diff compare --project admin --current ./custom-dir/

  # Fully manual (no project flag)
  ods screenshot-diff compare \
    --baseline s3://my-bucket/baselines/admin/main/ \
    --current ./web/output/screenshots/ \
    --output ./web/output/screenshot-diff/admin/index.html`,
		Run: func(cmd *cobra.Command, args []string) {
			runCompare(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Project, "project", "", "Project name (e.g. admin); sets sensible defaults for baseline, current, and output")
	cmd.Flags().StringVar(&opts.Rev, "rev", "", "Revision to compare against (default: main). Ignored when --from-rev/--to-rev are set")
	cmd.Flags().StringVar(&opts.FromRev, "from-rev", "", "Source (older) revision for cross-revision comparison")
	cmd.Flags().StringVar(&opts.ToRev, "to-rev", "", "Target (newer) revision for cross-revision comparison")
	cmd.Flags().StringVar(&opts.Baseline, "baseline", "", "Baseline directory or S3 URL (s3://...)")
	cmd.Flags().StringVar(&opts.Current, "current", "", "Current screenshots directory or S3 URL (s3://...)")
	cmd.Flags().StringVar(&opts.Output, "output", "", "Output path for the HTML report")
	cmd.Flags().Float64Var(&opts.Threshold, "threshold", 0.2, "Per-channel pixel difference threshold (0.0-1.0)")
	cmd.Flags().Float64Var(&opts.MaxDiffRatio, "max-diff-ratio", 0.01, "Max diff pixel ratio before marking as changed (informational)")

	return cmd
}

func newUploadBaselinesCommand() *cobra.Command {
	opts := &ScreenshotDiffUploadOptions{}

	cmd := &cobra.Command{
		Use:   "upload-baselines",
		Short: "Upload screenshots to S3 as new baselines",
		Long: `Upload a local directory of screenshots to S3 to serve as the new
baseline for future comparisons. Typically run after tests pass on the
main branch or a release branch.

Baselines are stored per-revision in S3:

  s3://<bucket>/baselines/<project>/<rev>/

When --project is specified, the following defaults are applied:
  --dir   → web/output/screenshots/
  --dest  → s3://<bucket>/baselines/<project>/<rev>/
  --rev   → main

Examples:

  # Upload baselines for main (default)
  ods screenshot-diff upload-baselines --project admin

  # Upload baselines for a release branch
  ods screenshot-diff upload-baselines --project admin --rev release/2.5

  # Upload baselines for a version tag
  ods screenshot-diff upload-baselines --project admin --rev v2.0.0

  # With delete (remove old baselines not in current set)
  ods screenshot-diff upload-baselines --project admin --delete

  # Fully manual
  ods screenshot-diff upload-baselines \
    --dir ./web/output/screenshots/ \
    --dest s3://onyx-playwright-artifacts/baselines/admin/main/`,
		Run: func(cmd *cobra.Command, args []string) {
			runUploadBaselines(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Project, "project", "", "Project name (e.g. admin); sets sensible defaults for dir and dest")
	cmd.Flags().StringVar(&opts.Rev, "rev", "", "Revision to store the baseline under (default: main)")
	cmd.Flags().StringVar(&opts.Dir, "dir", "", "Local directory containing screenshots to upload")
	cmd.Flags().StringVar(&opts.Dest, "dest", "", "S3 destination URL (s3://...)")
	cmd.Flags().BoolVar(&opts.Delete, "delete", false, "Delete S3 files not present locally")

	return cmd
}

// resolveCompareDefaults fills in missing flags from the --project default when set.
func resolveCompareDefaults(opts *ScreenshotDiffCompareOptions) {
	bucket := getS3Bucket()

	if opts.Project != "" {
		// Cross-revision mode: both sides come from S3
		if opts.FromRev != "" && opts.ToRev != "" {
			if opts.Baseline == "" {
				opts.Baseline = fmt.Sprintf("s3://%s/baselines/%s/%s/",
					bucket, opts.Project, sanitizeRev(opts.FromRev))
			}
			if opts.Current == "" {
				opts.Current = fmt.Sprintf("s3://%s/baselines/%s/%s/",
					bucket, opts.Project, sanitizeRev(opts.ToRev))
			}
		} else {
			// Standard mode: compare local screenshots against a revision
			rev := opts.Rev
			if rev == "" {
				rev = DefaultRev
			}
			if opts.Baseline == "" {
				opts.Baseline = fmt.Sprintf("s3://%s/baselines/%s/%s/",
					bucket, opts.Project, sanitizeRev(rev))
			}
			if opts.Current == "" {
				opts.Current = DefaultScreenshotDir
			}
		}

		if opts.Output == "" {
			opts.Output = filepath.Join(DefaultOutputDir, opts.Project, "index.html")
		}
	}

	// Fall back for output even without --project
	if opts.Output == "" {
		opts.Output = "screenshot-diff/index.html"
	}
}

// resolveUploadDefaults fills in missing flags from the --project default when set.
func resolveUploadDefaults(opts *ScreenshotDiffUploadOptions) {
	bucket := getS3Bucket()

	if opts.Project != "" {
		rev := opts.Rev
		if rev == "" {
			rev = DefaultRev
		}
		if opts.Dir == "" {
			opts.Dir = DefaultScreenshotDir
		}
		if opts.Dest == "" {
			opts.Dest = fmt.Sprintf("s3://%s/baselines/%s/%s/",
				bucket, opts.Project, sanitizeRev(rev))
		}
	}
}

// downloadS3Dir downloads an S3 URL into a local temporary directory and
// returns the path. The caller is responsible for cleaning up the directory.
func downloadS3Dir(s3URL string, prefix string) (string, error) {
	tmpDir, err := os.MkdirTemp("", prefix)
	if err != nil {
		return "", fmt.Errorf("failed to create temp directory: %w", err)
	}

	if err := s3.SyncDown(s3URL, tmpDir); err != nil {
		_ = os.RemoveAll(tmpDir)
		return "", fmt.Errorf("failed to download from S3 (%s): %w", s3URL, err)
	}

	return tmpDir, nil
}

func runCompare(opts *ScreenshotDiffCompareOptions) {
	// Validate cross-revision flags are used together
	if (opts.FromRev != "") != (opts.ToRev != "") {
		log.Fatal("--from-rev and --to-rev must be used together")
	}

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

	// Track temp dirs for cleanup
	var tempDirs []string
	defer func() {
		for _, d := range tempDirs {
			_ = os.RemoveAll(d)
		}
	}()

	// Resolve baseline directory
	baselineDir := opts.Baseline
	if strings.HasPrefix(opts.Baseline, "s3://") {
		dir, err := downloadS3Dir(opts.Baseline, "screenshot-baseline-*")
		if err != nil {
			log.Fatalf("Failed to download baselines: %v", err)
		}
		tempDirs = append(tempDirs, dir)
		baselineDir = dir
	}

	// Resolve current directory (may also be S3 in cross-revision mode)
	currentDir := opts.Current
	if strings.HasPrefix(opts.Current, "s3://") {
		dir, err := downloadS3Dir(opts.Current, "screenshot-current-*")
		if err != nil {
			log.Fatalf("Failed to download current screenshots: %v", err)
		}
		tempDirs = append(tempDirs, dir)
		currentDir = dir
	}

	// Verify baseline directory exists
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
	if _, err := os.Stat(currentDir); os.IsNotExist(err) {
		log.Warnf("Current screenshots directory does not exist: %s", currentDir)
		log.Warn("No screenshots captured for this project — writing empty summary.")

		summary := imgdiff.Summary{Project: project}
		if err := imgdiff.WriteSummary(summary, summaryPath); err != nil {
			log.Fatalf("Failed to write summary: %v", err)
		}
		log.Infof("Summary written to: %s", summaryPath)
		return
	}

	log.Infof("Comparing screenshots...")
	log.Infof("  Baseline: %s", opts.Baseline)
	log.Infof("  Current:  %s", opts.Current)
	log.Infof("  Threshold: %.2f", opts.Threshold)

	results, err := imgdiff.CompareDirectories(baselineDir, currentDir, opts.Threshold)
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

func runUploadBaselines(opts *ScreenshotDiffUploadOptions) {
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
