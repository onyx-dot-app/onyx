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
	HTML      string
	Markdown  string
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
			if code := runCoverage(args[0], opts); code != 0 {
				os.Exit(code)
			}
		},
	}

	cmd.Flags().BoolVar(&opts.Check, "check", false, "Fail when a package drops below its baseline floor")
	cmd.Flags().BoolVar(&opts.Update, "update", false, "Rewrite the baseline from this run")
	cmd.Flags().StringVar(&opts.Profile, "profile", "", "Keep the coverage profile at this path, for go tool cover -html")
	cmd.Flags().StringVar(&opts.HTML, "html", "", "Render the profile as a browsable page at this path")
	cmd.Flags().StringVar(&opts.Markdown, "markdown", "", "Write the changed packages as a markdown table at this path, for a PR comment")
	cmd.Flags().Float64Var(&opts.Tolerance, "tolerance", coverage.DefaultTolerance,
		"Percentage points a package may drop below its floor without failing")

	return cmd
}

// runCoverage returns the process exit code rather than exiting, so the
// temporary profile directory is always removed on the way out.
func runCoverage(target string, opts *CoverageOptions) int {
	if opts.Check && opts.Update {
		log.Fatal("--check and --update do the opposite of each other; pass only one")
	}
	if err := coverage.ValidateTolerance(opts.Tolerance); err != nil {
		log.Fatalf("Invalid --tolerance: %v", err)
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

	profilePath, cleanup := outputTarget(opts.Profile, "coverage.out")
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
		return exitErr.Code
	}
	if err != nil {
		log.Errorf("Failed to measure coverage: %v", err)
		return 1
	}

	if opts.HTML != "" {
		htmlPath, err := filepath.Abs(opts.HTML)
		if err != nil {
			log.Errorf("Failed to resolve the html path %q: %v", opts.HTML, err)
			return 1
		}
		if err := coverage.WriteHTML(moduleDir, profilePath, htmlPath); err != nil {
			log.Errorf("Failed to render the html report: %v", err)
			return 1
		}
		log.Infof("HTML report written to %s", htmlPath)
	}

	if opts.Profile != "" {
		log.Infof("Coverage profile written to %s", profilePath)
		log.Infof("Browse it with: go tool cover -html=%s", profilePath)
	}

	return runCoverageGate(coverageGate{
		Kind:         coverage.GoTests,
		Profile:      profile,
		BaselinePath: coverage.GoTests.BaselinePath(moduleDir),
		Name:         suite.Dir,
		Command:      "ods coverage " + suite.Name,
		Check:        opts.Check,
		Update:       opts.Update,
		Markdown:     opts.Markdown,
		Tolerance:    opts.Tolerance,
	})
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
