package cmd

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/coverage"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/testsuite"
)

// CoverageOptions holds options for the coverage command.
type CoverageOptions struct {
	Check     bool
	Update    bool
	Profile   string
	Tolerance float64
}

// NewCoverageCommand creates a command that measures statement coverage for a
// Go suite and compares it against the committed baseline.
func NewCoverageCommand() *cobra.Command {
	opts := &CoverageOptions{}

	cmd := &cobra.Command{
		Use:   "coverage <suite|module-dir>",
		Short: "Measure Go test coverage and hold it against a baseline",
		Long:  coverageHelpDescription(),
		Args:  cobra.ExactArgs(1),
		ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
			if len(args) > 0 {
				return nil, cobra.ShellCompDirectiveNoFileComp
			}
			return testsuite.Names(), cobra.ShellCompDirectiveNoFileComp
		},
		Run: func(cmd *cobra.Command, args []string) {
			runCoverage(args[0], opts)
		},
	}

	cmd.Flags().BoolVar(&opts.Check, "check", false, "Fail when a package drops below its baseline floor")
	cmd.Flags().BoolVar(&opts.Update, "update", false, "Rewrite the baseline from this run")
	cmd.Flags().StringVar(&opts.Profile, "profile", "", "Keep the coverage profile at this path, for go tool cover -html")
	cmd.Flags().Float64Var(&opts.Tolerance, "tolerance", coverage.DefaultTolerance,
		"Percentage points a package may drop below its floor without failing")

	return cmd
}

func runCoverage(target string, opts *CoverageOptions) {
	if opts.Check && opts.Update {
		log.Fatal("--check and --update do the opposite of each other; pass only one")
	}

	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}
	cwd, err := os.Getwd()
	if err != nil {
		log.Fatalf("Failed to determine the working directory: %v", err)
	}

	suite := coverageSuite(root, cwd, target)
	moduleDir := filepath.Join(root, suite.Dir)

	profilePath, cleanup := profileTarget(opts.Profile)
	defer cleanup()

	log.Infof("Measuring %s coverage...", suite.Name)
	profile, err := coverage.Run(coverage.RunOptions{
		ModuleDir:   moduleDir,
		ProfilePath: profilePath,
		Args:        suite.DefaultArgs,
		Stdout:      os.Stdout,
		Stderr:      os.Stderr,
	})
	var exitErr *coverage.ExitError
	if errors.As(err, &exitErr) {
		// The tests failed, and their output is already on the terminal.
		// Coverage from a failed run is not worth reporting.
		os.Exit(exitErr.Code)
	}
	if err != nil {
		log.Fatalf("Failed to measure coverage: %v", err)
	}

	baselinePath := coverage.BaselinePath(moduleDir)

	if opts.Update {
		writeBaseline(baselinePath, profile)
		return
	}

	baseline, err := coverage.LoadBaseline(baselinePath)
	if errors.Is(err, os.ErrNotExist) {
		if opts.Check {
			log.Fatalf("No baseline at %s. Create one with: ods coverage %s --update", baselinePath, suite.Name)
		}
		log.Warnf("No baseline at %s; create one with: ods coverage %s --update", baselinePath, suite.Name)
		baseline = nil
	} else if err != nil {
		log.Fatalf("Failed to read the baseline: %v", err)
	}

	report := coverage.Compare(profile, baseline, opts.Tolerance)
	if err := coverage.WriteReport(os.Stdout, report); err != nil {
		log.Fatalf("Failed to write the report: %v", err)
	}

	if profilePath == opts.Profile {
		log.Infof("Coverage profile written to %s", profilePath)
		log.Infof("Browse it with: go tool cover -html=%s", profilePath)
	}

	if improvements := report.Improvements(); len(improvements) > 0 {
		log.Infof("%d package(s) rose above the baseline. Lock the gain in with: ods coverage %s --update",
			len(improvements), suite.Name)
	}

	if !opts.Check {
		return
	}
	regressions := report.Regressions()
	if len(regressions) == 0 {
		log.Infof("Coverage holds at or above the baseline in %s", baselinePath)
		return
	}
	for _, regression := range regressions {
		log.Errorf("%s fell to %.1f%%, below its %.1f%% floor", regression.Package, regression.Percent, regression.Floor)
	}
	log.Fatalf("Coverage regressed in %d package(s). Add tests, or justify the drop and run: ods coverage %s --update",
		len(regressions), suite.Name)
}

func writeBaseline(baselinePath string, profile *coverage.Profile) {
	baseline := coverage.NewBaseline(profile)
	if err := baseline.Save(baselinePath); err != nil {
		log.Fatalf("Failed to write the baseline: %v", err)
	}
	// Report the floor that was recorded, not the raw measurement, so the
	// number here matches the file.
	log.Infof("Wrote %s with a %.1f%% total coverage floor across %d packages",
		baselinePath, baseline.Total, len(baseline.Packages))
}

// profileTarget resolves where the coverage profile is written. Without an
// explicit path it goes to a temporary file that is removed afterwards.
func profileTarget(requested string) (string, func()) {
	if requested != "" {
		return requested, func() {}
	}
	dir, err := os.MkdirTemp("", "ods-coverage")
	if err != nil {
		log.Fatalf("Failed to create a temporary directory: %v", err)
	}
	return filepath.Join(dir, "coverage.out"), func() { _ = os.RemoveAll(dir) }
}

// coverageSuite resolves a suite from a suite name or a module directory,
// reusing the routing `ods test` uses. Accepting a directory lets CI pass the
// module it is iterating over without a second name-to-path table.
func coverageSuite(root, cwd, target string) *testsuite.Suite {
	suite, args, err := testsuite.Resolve(root, cwd, []string{target})
	if err != nil {
		log.Fatalf("%v", err)
	}
	// Coverage is measured for a whole module, since a baseline covers every
	// package in it. A path pointing deeper would silently measure less.
	if len(args) > 0 && args[0] != "./..." {
		log.Fatalf("Coverage runs a whole module; %q points inside %s. Use: ods coverage %s",
			target, suite.Dir, suite.Name)
	}
	return suite
}

func coverageHelpDescription() string {
	var b strings.Builder
	b.WriteString(`Measure Go statement coverage and hold it against a committed baseline.

The baseline is a ` + coverage.BaselineFile + ` at the module root recording each
package's floor. --check fails when a package drops below its floor, which is how
CI keeps coverage from regressing. After adding tests, --update raises the floors.

Coverage is per package: a package's number counts only its own tests, so it is a
number that package's owner can act on.

Examples:
  ods coverage ods                  # report where each package stands
  ods coverage ods --check          # fail on a regression (what CI runs)
  ods coverage ods --update         # record today's numbers as the new floors
  ods coverage ods --profile /tmp/cover.out

Suites:`)
	for _, suite := range testsuite.All() {
		fmt.Fprintf(&b, "\n  %-12s %s", suite.Name, suite.Short)
	}
	return b.String()
}
