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
	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
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
	// FromProfile reports from a profile an earlier run kept, without running
	// the tests. CI measures without credentials, then reports with them.
	FromProfile string
	// Base reports the run against the coverage snapshot of this commit-ish
	// instead of the floors. The gate keeps using the floors.
	Base           string
	Publish        bool
	SnapshotBucket string
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
	cmd.Flags().StringVar(&opts.FromProfile, "from-profile", "",
		"Report from this coverage profile instead of running the tests")
	cmd.Flags().StringVar(&opts.Base, "base", "",
		"Report against the coverage snapshot of this commit, or its nearest recorded ancestor, instead of the floors")
	cmd.Flags().BoolVar(&opts.Publish, "publish", false,
		"Record this run as the coverage snapshot of HEAD (needs AWS credentials)")
	cmd.Flags().StringVar(&opts.SnapshotBucket, "snapshot-bucket", DefaultS3Bucket,
		"S3 bucket that holds the coverage snapshots")

	return cmd
}

// runCoverage returns the process exit code rather than exiting, so the
// temporary profile directory is always removed on the way out.
func runCoverage(target string, opts *CoverageOptions) int {
	if opts.Check && opts.Update {
		log.Fatal("--check and --update do the opposite of each other; pass only one")
	}
	if opts.Base != "" && opts.Update {
		log.Fatal("--base reports against a snapshot, --update rewrites the floors; pass only one")
	}
	if opts.Publish && opts.Update {
		log.Fatal("--publish records this run as a snapshot, --update rewrites the floors; pass only one")
	}
	if opts.FromProfile != "" && opts.Profile != "" {
		log.Fatal("--from-profile reads a profile, --profile keeps the one this run writes; pass only one")
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

	var profile *coverage.Profile
	var profilePath string
	var code int
	if opts.FromProfile != "" {
		profile, profilePath, code = loadProfile(moduleDir, opts.FromProfile)
	} else {
		var cleanup func()
		profilePath, cleanup = outputTarget(opts.Profile, "coverage.out")
		defer cleanup()
		profile, code = measureCoverage(suite, moduleDir, profilePath)
	}
	if code != 0 {
		return code
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

	store := coverage.NewS3SnapshotStore(opts.SnapshotBucket, suite.Dir)
	var baseReference *coverage.Reference
	if opts.Base != "" {
		var code int
		if baseReference, code = locateBaseReference(opts.Base, store); code != 0 {
			return code
		}
	}

	if code := runCoverageGate(coverageGate{
		Kind:            coverage.GoTests,
		Profile:         profile,
		BaselinePath:    coverage.GoTests.BaselinePath(moduleDir),
		Name:            suite.Dir,
		Command:         "ods coverage " + suite.Name,
		Check:           opts.Check,
		Update:          opts.Update,
		Markdown:        opts.Markdown,
		Tolerance:       opts.Tolerance,
		ReportReference: baseReference,
	}); code != 0 {
		return code
	}

	// Publishing runs last: a snapshot describes a run whose tests and gate
	// both passed.
	if opts.Publish {
		return publishSnapshot(store, profile, suite.Dir)
	}
	return 0
}

// measureCoverage runs the suite's tests with a profile at profilePath.
func measureCoverage(suite *testsuite.Suite, moduleDir, profilePath string) (*coverage.Profile, int) {
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
		return nil, exitErr.Code
	}
	if err != nil {
		log.Errorf("Failed to measure coverage: %v", err)
		return nil, 1
	}
	return profile, 0
}

// loadProfile reads a profile an earlier run kept with --profile and returns
// it with its absolute path, which the html renderer needs.
func loadProfile(moduleDir, path string) (*coverage.Profile, string, int) {
	profilePath, err := filepath.Abs(path)
	if err != nil {
		log.Errorf("Failed to resolve the profile path %q: %v", path, err)
		return nil, "", 1
	}
	modulePath, err := coverage.ModulePath(moduleDir)
	if err != nil {
		log.Errorf("Failed to read the module path: %v", err)
		return nil, "", 1
	}
	profile, err := coverage.ParseProfileFile(profilePath, modulePath)
	if err != nil {
		log.Errorf("Failed to read the coverage profile: %v", err)
		return nil, "", 1
	}
	log.Infof("Reporting from the coverage profile at %s", profilePath)
	return profile, profilePath, 0
}

// locateBaseReference finds the snapshot to report against. A missing snapshot
// is normal, for example on a fork pull request that holds no credentials, so
// it warns and returns a nil reference to keep the floors.
func locateBaseReference(rev string, store coverage.SnapshotStore) (*coverage.Reference, int) {
	match, err := coverage.LocateBaseSnapshot(rev, coverage.GitCommitHistory{}, store, coverage.DefaultBaseWalkLimit)
	if errors.Is(err, coverage.ErrBaseSnapshotUnavailable) {
		log.Warnf("%v; reporting against the floors", err)
		return nil, 0
	}
	if err != nil {
		log.Errorf("Failed to look up the base coverage snapshot: %v", err)
		return nil, 1
	}

	log.Infof("Reporting against the snapshot of %s", coverage.ShortCommit(match.Commit))
	if match.Distance > 0 {
		log.Infof("The base %s has no snapshot; the nearest recorded ancestor is %d commit(s) back",
			coverage.ShortCommit(match.Base), match.Distance)
	}
	return match.Snapshot.Reference(), 0
}

// publishSnapshot records this run as the coverage snapshot of HEAD.
func publishSnapshot(store *coverage.S3SnapshotStore, profile *coverage.Profile, module string) int {
	// A snapshot is keyed by commit, so it must describe that commit alone.
	changes, err := git.WorkingTreeChanges()
	if err != nil {
		log.Errorf("Failed to inspect the working tree: %v", err)
		return 1
	}
	if len(changes) > 0 {
		log.Errorf("Refusing to publish a snapshot: the working tree differs from HEAD:\n%s",
			strings.Join(changes, "\n"))
		return 1
	}
	commit, err := git.ResolveCommit("HEAD")
	if err != nil {
		log.Errorf("Failed to resolve HEAD: %v", err)
		return 1
	}
	if err := store.Publish(coverage.NewSnapshot(profile, commit, module)); err != nil {
		log.Errorf("Failed to publish the coverage snapshot: %v", err)
		return 1
	}
	log.Infof("Published the coverage snapshot of %s to %s", coverage.ShortCommit(commit), store.ObjectURL(commit))
	return 0
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

--from-profile reports from a profile an earlier run kept with --profile,
without running the tests again.

--base reports against the coverage snapshot of a commit, or of its nearest
recorded ancestor, instead of against the floors, which shows what a branch
changed. A missing snapshot only warns: the report falls back to the floors.
--publish records a successful run as the snapshot of HEAD. Neither flag
changes what --check gates on.

Examples:
  ods coverage ods                  # report where each package stands
  ods coverage ods --check          # fail on a regression (what CI runs)
  ods coverage ods --update         # record today's numbers as the new floors
  ods coverage ods --profile /tmp/cover.out
  ods coverage ods --base origin/main   # report what this branch changed

Suites:`)
	for _, suite := range testsuite.All() {
		fmt.Fprintf(&b, "\n  %-12s %s", suite.Name, suite.Short)
	}
	return b.String()
}
