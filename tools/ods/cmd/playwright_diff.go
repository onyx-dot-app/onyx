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

// PlaywrightDiffCompareOptions holds options for the compare subcommand.
type PlaywrightDiffCompareOptions struct {
	Baseline     string
	Current      string
	Output       string
	Threshold    float64
	MaxDiffRatio float64
}

// PlaywrightDiffUploadOptions holds options for the upload-baselines subcommand.
type PlaywrightDiffUploadOptions struct {
	Dir    string
	Dest   string
	Delete bool
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

Example usage:

  # Compare local directories
  ods playwright-diff compare --baseline ./baselines --current ./screenshots

  # Compare against S3 baselines
  ods playwright-diff compare --baseline s3://bucket/baselines/admin/ --current ./screenshots

  # Upload new baselines to S3
  ods playwright-diff upload-baselines --dir ./screenshots --dest s3://bucket/baselines/admin/`,
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
a self-contained HTML visual diff report.

The --baseline flag accepts either a local directory path or an S3 URL
(s3://bucket/prefix/). When an S3 URL is provided, baselines are downloaded
to a temporary directory before comparison.

Examples:

  # Local comparison
  ods playwright-diff compare \
    --baseline ./baselines \
    --current ./screenshots \
    --output ./report/index.html

  # Compare against S3 baselines
  ods playwright-diff compare \
    --baseline s3://onyx-playwright-artifacts/baselines/admin/ \
    --current ./web/screenshots/ \
    --output ./visual-diff/index.html`,
		Run: func(cmd *cobra.Command, args []string) {
			runCompare(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Baseline, "baseline", "", "Baseline directory or S3 URL (s3://...)")
	cmd.Flags().StringVar(&opts.Current, "current", "", "Current screenshots directory")
	cmd.Flags().StringVar(&opts.Output, "output", "visual-diff/index.html", "Output path for the HTML report")
	cmd.Flags().Float64Var(&opts.Threshold, "threshold", 0.2, "Per-channel pixel difference threshold (0.0-1.0)")
	cmd.Flags().Float64Var(&opts.MaxDiffRatio, "max-diff-ratio", 0.01, "Max diff pixel ratio before marking as changed (informational)")

	_ = cmd.MarkFlagRequired("baseline")
	_ = cmd.MarkFlagRequired("current")

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

Examples:

  # Upload to default location
  ods playwright-diff upload-baselines \
    --dir ./web/screenshots/ \
    --dest s3://onyx-playwright-artifacts/baselines/admin/

  # Upload with delete (remove old baselines not in current set)
  ods playwright-diff upload-baselines \
    --dir ./web/screenshots/ \
    --dest s3://onyx-playwright-artifacts/baselines/admin/ \
    --delete`,
		Run: func(cmd *cobra.Command, args []string) {
			runUploadBaselines(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Dir, "dir", "", "Local directory containing screenshots to upload")
	cmd.Flags().StringVar(&opts.Dest, "dest", "", "S3 destination URL (s3://...)")
	cmd.Flags().BoolVar(&opts.Delete, "delete", false, "Delete S3 files not present locally")

	_ = cmd.MarkFlagRequired("dir")
	_ = cmd.MarkFlagRequired("dest")

	return cmd
}

func runCompare(opts *PlaywrightDiffCompareOptions) {
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

	if _, err := os.Stat(opts.Current); os.IsNotExist(err) {
		log.Fatalf("Current screenshots directory does not exist: %s", opts.Current)
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

	// Generate HTML report
	outputPath := opts.Output
	if !filepath.IsAbs(outputPath) {
		cwd, err := os.Getwd()
		if err != nil {
			log.Fatalf("Failed to get working directory: %v", err)
		}
		outputPath = filepath.Join(cwd, outputPath)
	}

	log.Infof("Generating report: %s", outputPath)
	if err := imgdiff.GenerateReport(results, outputPath); err != nil {
		log.Fatalf("Failed to generate report: %v", err)
	}

	log.Infof("Report generated successfully: %s", outputPath)
}

func runUploadBaselines(opts *PlaywrightDiffUploadOptions) {
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
