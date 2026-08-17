package cmd

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/testsuite"
)

// TestOptions holds options for the test command.
type TestOptions struct {
	NoEE     bool
	Parallel bool
}

// NewTestCommand creates a command that runs any of the repo's test suites.
func NewTestCommand() *cobra.Command {
	opts := &TestOptions{}

	cmd := &cobra.Command{
		Use:   "test [suite|path] [args...]",
		Short: "Run tests for any suite in the repo",
		Long:  testHelpDescription(),
		Args:  cobra.ArbitraryArgs,
		ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
			if len(args) > 0 {
				return nil, cobra.ShellCompDirectiveDefault
			}
			return testsuite.Names(), cobra.ShellCompDirectiveNoFileComp
		},
		Run: func(cmd *cobra.Command, args []string) {
			runTest(cmd, args, opts)
		},
	}
	// Stop parsing at the first positional so flags meant for pytest, jest, or
	// playwright reach them instead of cobra.
	cmd.Flags().SetInterspersed(false)

	cmd.Flags().BoolVar(&opts.NoEE, "no-ee", false, "Disable Enterprise Edition features (enabled by default)")
	cmd.Flags().BoolVarP(&opts.Parallel, "parallel", "p", false, "Run pytest suites in parallel (pytest-xdist -n auto)")

	return cmd
}

func runTest(cmd *cobra.Command, args []string, opts *TestOptions) {
	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}
	cwd, err := os.Getwd()
	if err != nil {
		log.Fatalf("Failed to determine the working directory: %v", err)
	}

	suite, suiteArgs, err := testsuite.Resolve(root, cwd, args)
	if errors.Is(err, testsuite.ErrNoArgs) {
		_ = cmd.Help()
		os.Exit(1)
	}
	if err != nil {
		log.Fatal(err)
	}

	suiteArgs = dropSeparator(suiteArgs)

	switch suite.Runner {
	case testsuite.RunnerPytest:
		runPytestSuite(root, suite, suiteArgs, opts)
	case testsuite.RunnerJest:
		runJestSuite(root, suite, suiteArgs)
	case testsuite.RunnerPlaywright:
		runPlaywrightSuite(root, suite, suiteArgs)
	default:
		log.Fatalf("Suite %s has no runner", suite.Name)
	}
}

// dropSeparator removes the first "--" from the arguments. Writing it is habit
// for anyone used to `bun run` or `npm test`, and it can land either before or
// after a path. No runner we wrap wants a literal "--", which pytest would
// read as a target rather than a separator.
func dropSeparator(args []string) []string {
	for i, arg := range args {
		if arg == "--" {
			return append(args[:i:i], args[i+1:]...)
		}
	}
	return args
}

// runPytestSuite runs a backend suite from the backend directory, so that
// backend/pytest.ini applies. Credentials come from .vscode/.env the same way
// `ods backend` supplies them, which also creates that file from the template
// on first use.
func runPytestSuite(root string, suite *testsuite.Suite, suiteArgs []string, opts *TestOptions) {
	pytestArgs := []string{"run", "pytest"}
	pytestArgs = append(pytestArgs, suite.DefaultArgs...)
	if opts.Parallel {
		pytestArgs = append(pytestArgs, "-n", "auto")
	}
	if len(suiteArgs) > 0 {
		pytestArgs = append(pytestArgs, suiteArgs...)
	} else {
		pytestArgs = append(pytestArgs, suite.Target)
	}

	envVars := eeEnvDefaults(opts.NoEE)
	if suite.NeedsBackendEnv {
		envFile := ensureBackendEnvFile(root)
		envVars = append(loadBackendEnvFile(envFile), envVars...)
		log.Debugf("Applied %d env vars from %s (shell takes precedence)", len(envVars), envFile)
	}

	suiteDir := filepath.Join(root, suite.Dir)
	log.Infof("Running %s tests...", suite.Name)
	log.Debugf("Running in %s: uv %v", suiteDir, pytestArgs)

	pytestCmd := exec.Command("uv", pytestArgs...)
	pytestCmd.Dir = suiteDir
	pytestCmd.Env = mergeEnv(os.Environ(), envVars)
	runChild(pytestCmd, "pytest")
}

func runJestSuite(root string, suite *testsuite.Suite, suiteArgs []string) {
	runBunScript(root, suite, "test", suiteArgs)
}

func runPlaywrightSuite(root string, suite *testsuite.Suite, suiteArgs []string) {
	// The playwright script, never bunx, so the pinned version is the one that
	// runs. See web/AGENTS.md.
	runBunScript(root, suite, "playwright", suiteArgs)
}

// runBunScript runs a package.json script for a bun-based suite, after making
// sure the suite's dependencies are installed.
func runBunScript(root string, suite *testsuite.Suite, script string, suiteArgs []string) {
	suiteDir := filepath.Join(root, suite.Dir)
	if suite.Dir == "web" {
		// Reuses the dependency and workspace-library checks `ods web` runs.
		suiteDir = prepareWebDir()
	} else {
		ensureNodeModules(suiteDir)
	}

	bunArgs := []string{"run", script}
	if len(suiteArgs) > 0 {
		// bun requires "--" to forward arguments to the underlying script.
		bunArgs = append(bunArgs, "--")
		bunArgs = append(bunArgs, suiteArgs...)
	}

	log.Infof("Running %s tests...", suite.Name)
	log.Debugf("Running in %s: bun %v", suiteDir, bunArgs)

	bunCmd := exec.Command("bun", bunArgs...)
	bunCmd.Dir = suiteDir
	runChild(bunCmd, "bun")
}

// ensureNodeModules installs dependencies for a bun package that has none yet.
// Suites outside web/ have no lockfile stamp to compare against, so this only
// covers the empty case.
func ensureNodeModules(dir string) {
	entries, err := os.ReadDir(filepath.Join(dir, "node_modules"))
	if err == nil && len(entries) > 0 {
		return
	}

	log.Infof("node_modules missing in %s, running bun install...", dir)
	installCmd := exec.Command("bun", "install")
	installCmd.Dir = dir
	runChild(installCmd, "bun install")
}

func testHelpDescription() string {
	description := `Run tests for any suite in the repo.

The first argument is a suite name or a path inside a suite. A path picks the
suite that covers it, so you can pass a file straight from an editor. Every
later argument goes to the underlying runner.

Examples:
  ods test unit
  ods test backend/tests/unit/onyx/test_foo.py::test_bar
  ods test unit -- -k some_name
  ods test external --parallel
  ods test web -- --watch
  ods test web/tests/e2e/chat.spec.ts

Suites:`

	var b strings.Builder
	b.WriteString(description)
	for _, suite := range testsuite.All() {
		names := suite.Name
		if len(suite.Aliases) > 0 {
			names += ", " + strings.Join(suite.Aliases, ", ")
		}
		fmt.Fprintf(&b, "\n  %-28s %s", names, suite.Short)
	}
	return b.String()
}
