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

	"github.com/onyx-dot-app/onyx/tools/ods/internal/childproc"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/testsuite"
)

// NewTestCommand creates a command that runs the repo's Go test suites.
func NewTestCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "test [suite|path] [args...]",
		Short: "Run tests for the repo's Go modules",
		Long:  testHelpDescription(),
		Args:  cobra.ArbitraryArgs,
		ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
			if len(args) > 0 {
				return nil, cobra.ShellCompDirectiveDefault
			}
			return testsuite.Names(), cobra.ShellCompDirectiveNoFileComp
		},
		Run: runTest,
	}
	// Stop parsing at the first positional so flags meant for go test reach
	// it instead of cobra.
	cmd.Flags().SetInterspersed(false)

	return cmd
}

func runTest(cmd *cobra.Command, args []string) {
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

	runGoSuite(root, suite, dropSeparator(suiteArgs))
}

// dropSeparator removes the first "--" from the arguments. Writing it is habit
// for anyone used to `bun run` or `npm test`, and it can land either before or
// after a path. go test would read a literal "--" as a package pattern rather
// than a separator.
func dropSeparator(args []string) []string {
	for i, arg := range args {
		if arg == "--" {
			return append(args[:i:i], args[i+1:]...)
		}
	}
	return args
}

// runGoSuite runs a Go module's tests from the module directory, which is where
// go test resolves its "./..." package patterns.
func runGoSuite(root string, suite *testsuite.Suite, suiteArgs []string) {
	goArgs := []string{"test"}
	goArgs = append(goArgs, suite.DefaultArgs...)
	// go test with no packages tests only the module root, so a bare run gets
	// "./..." to cover the whole module.
	if !testsuite.HasTarget(suiteArgs) {
		goArgs = append(goArgs, "./...")
	}
	goArgs = append(goArgs, suiteArgs...)

	suiteDir := filepath.Join(root, suite.Dir)
	log.Infof("Running %s tests...", suite.Name)
	log.Debugf("Running in %s: go %v", suiteDir, goArgs)

	goCmd := exec.Command("go", goArgs...)
	goCmd.Dir = suiteDir
	childproc.Run(goCmd, "go test")
}

func testHelpDescription() string {
	description := `Run tests for the repo's Go modules.

The first argument is a suite name or a path inside a module. A path picks the
suite that covers it, so you can pass a file straight from an editor. Every
later argument goes to go test.

go test takes packages rather than files, so a file argument runs the package
that holds it, and "<file>::<TestName>" becomes a -run filter.

Examples:
  ods test ods
  ods test tools/ods/internal/testsuite
  ods test tools/ods/internal/testsuite/testsuite_test.go::TestResolveGoTargets
  ods test cli -run TestChat -v

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
