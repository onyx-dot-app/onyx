package cmd

import (
	"errors"
	"os"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/coverage"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/typecoverage"
)

// TypeCoverageOptions holds options for the type-coverage command.
type TypeCoverageOptions struct {
	Check     bool
	Update    bool
	Markdown  string
	Output    string
	Tolerance float64
}

// NewTypeCoverageCommand creates a command that type-checks, measures type
// coverage and compares it against the committed baseline. Only TypeScript is
// supported: ty does not report type coverage yet.
func NewTypeCoverageCommand() *cobra.Command {
	opts := &TypeCoverageOptions{}

	cmd := &cobra.Command{
		Use:       "type-coverage <checker>",
		Short:     "Type-check, then hold type coverage against a baseline",
		Long:      typeCoverageHelpDescription(),
		Args:      cobra.ExactArgs(1),
		ValidArgs: []string{"typescript", "ts"},
		Run: func(cmd *cobra.Command, args []string) {
			if code := runTypeCoverage(args[0], opts); code != 0 {
				os.Exit(code)
			}
		},
	}

	cmd.Flags().BoolVar(&opts.Check, "check", false, "Fail when a directory drops below its baseline floor")
	cmd.Flags().BoolVar(&opts.Update, "update", false, "Rewrite the baseline from this run")
	cmd.Flags().StringVar(&opts.Markdown, "markdown", "", "Write the changed directories as a markdown table at this path, for a PR comment")
	cmd.Flags().StringVar(&opts.Output, "output", "", "Keep the per-file counts as JSON at this path")
	cmd.Flags().Float64Var(&opts.Tolerance, "tolerance", coverage.TypeScript.DefaultTolerance,
		"Percentage points a directory may drop below its floor without failing")

	return cmd
}

// runTypeCoverage returns the process exit code rather than exiting, so the
// temporary output directory is always removed on the way out.
func runTypeCoverage(checker string, opts *TypeCoverageOptions) int {
	if checker != "typescript" && checker != "ts" {
		log.Fatalf("Unknown checker %q. Supported: typescript (alias: ts)", checker)
	}
	if opts.Check && opts.Update {
		log.Fatal("--check and --update do the opposite of each other; pass only one")
	}
	if err := coverage.ValidateTolerance(opts.Tolerance); err != nil {
		log.Fatalf("Invalid --tolerance: %v", err)
	}

	dir, err := webDir()
	if err != nil {
		log.Fatalf("Failed to find web directory: %v", err)
	}
	prepareWebDir(dir)

	outputPath, cleanup := outputTarget(opts.Output, "type-coverage.json")
	defer cleanup()

	log.Info("Type-checking web/ and measuring type coverage...")
	files, err := typecoverage.Run(typecoverage.RunOptions{
		WebDir:     dir,
		OutputPath: outputPath,
		Stdout:     os.Stdout,
		Stderr:     os.Stderr,
	})
	var exitErr *coverage.ExitError
	if errors.As(err, &exitErr) {
		// The script output is already on the terminal.
		return exitErr.Code
	}
	if err != nil {
		log.Errorf("Failed to measure type coverage: %v", err)
		return 1
	}
	if opts.Output != "" {
		log.Infof("Per-file counts written to %s", outputPath)
	}

	return runCoverageGate(coverageGate{
		Kind:         coverage.TypeScript,
		Profile:      typecoverage.Aggregate(files, typecoverage.Depth),
		BaselinePath: coverage.TypeScript.BaselinePath(dir),
		Name:         "web",
		Command:      "ods type-coverage typescript",
		Check:        opts.Check,
		Update:       opts.Update,
		Markdown:     opts.Markdown,
		Tolerance:    opts.Tolerance,
	})
}

func typeCoverageHelpDescription() string {
	return `Type-check, measure type coverage, and hold it against a committed baseline.

Type coverage is the share of identifiers whose type is not ` + "`any`" + `. Each report
row is a directory, at most three names deep, e.g. src/app/admin.

A type error fails the command before the coverage is compared.

The baseline is web/` + coverage.TypeBaselineFile + `. --check fails when a directory
drops below its floor, which is how CI keeps ` + "`any`" + ` from spreading. After removing
` + "`any`" + ` types, --update raises the floors.

For the type check and the total only, run: ods web types:check

Checkers:
  typescript (ts)  web/, type-checked and measured with TypeScript 7

Examples:
  ods type-coverage ts              # report where each directory stands
  ods type-coverage ts --check      # fail on a regression (what CI runs)
  ods type-coverage ts --update     # record today's numbers as the new floors`
}
