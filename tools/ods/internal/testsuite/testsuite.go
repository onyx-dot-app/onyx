// Package testsuite maps a suite name or a file path onto the Go module that
// owns it. The repo has three Go modules with different working directories;
// this package holds the routing table and the pure logic that picks an entry
// from it.
package testsuite

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// ErrNoArgs is returned when no suite or path was given.
var ErrNoArgs = errors.New("no suite or path given")

// Suite describes one test suite and how to run it.
type Suite struct {
	// Name is the canonical name accepted on the command line.
	Name string
	// Aliases are alternate names accepted on the command line.
	Aliases []string
	// Dir is the module directory, relative to the git root. It is the
	// working directory for go test and the prefix used to infer the suite
	// from a path.
	Dir string
	// DefaultArgs are passed to go test before any user arguments, so a
	// user argument for the same option still wins.
	DefaultArgs []string
	// Short is the one-line description shown in help output.
	Short string
}

// suites is the routing table. Order here is the order shown in help.
var suites = []Suite{
	{
		Name: "ods",
		Dir:  "tools/ods",
		// -race matches pr-golang-tests.yml, which runs every Go module.
		DefaultArgs: []string{"-race"},
		Short:       "Tests for this tool (go)",
	},
	{
		Name:        "cli",
		Dir:         "cli",
		DefaultArgs: []string{"-race"},
		Short:       "Onyx CLI tests (go)",
	},
	{
		Name:        "terraform",
		Aliases:     []string{"tf"},
		Dir:         "terraform-provider-onyx",
		DefaultArgs: []string{"-race"},
		Short:       "Terraform provider tests (go)",
	},
}

// All returns every suite, in help order.
func All() []Suite {
	out := make([]Suite, len(suites))
	copy(out, suites)
	return out
}

// Names returns every accepted suite name, without aliases, in help order.
func Names() []string {
	names := make([]string, 0, len(suites))
	for i := range suites {
		names = append(names, suites[i].Name)
	}
	return names
}

// byName looks up a suite by its canonical name or one of its aliases.
func byName(name string) *Suite {
	for i := range suites {
		if suites[i].Name == name {
			return &suites[i]
		}
		for _, alias := range suites[i].Aliases {
			if alias == name {
				return &suites[i]
			}
		}
	}
	return nil
}

// Resolve picks the suite for args. The first argument is either a suite name,
// an alias, or a path inside a suite. Paths are rewritten relative to the
// suite's working directory, which is where the runner is started, and the
// remaining arguments pass through untouched.
//
// root is the git root. cwd is the caller's working directory, so that a path
// typed relative to it (for example inside tools/ods/) resolves correctly.
func Resolve(root, cwd string, args []string) (*Suite, []string, error) {
	if len(args) == 0 {
		return nil, nil, ErrNoArgs
	}

	first := args[0]

	if suite := byName(first); suite != nil {
		return suite, relocate(root, cwd, suite, args[1:]), nil
	}

	repoPath, ok := repoRelative(root, cwd, first)
	if !ok {
		return nil, nil, fmt.Errorf("%q is neither a suite name nor an existing path (suites: %s)",
			first, strings.Join(Names(), ", "))
	}

	suite := suiteForPath(repoPath)
	if suite == nil {
		return nil, nil, fmt.Errorf("no test suite covers %q (suites: %s)",
			first, strings.Join(Names(), ", "))
	}

	target, err := filepath.Rel(suite.Dir, repoPath)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to place %q inside %s: %w", first, suite.Dir, err)
	}

	// The first argument is always rewritten: it is known to be a target, so
	// the bare-word caution that applies to later arguments is not needed.
	rest := relocate(root, cwd, suite, args[1:])
	return suite, append(runnerTarget(root, suite, path(target)), rest...), nil
}

// runnerTarget shapes a suite-relative path into what go test accepts. go test
// takes packages rather than files, so a file becomes the directory that holds
// it, and a "<file>::<TestName>" node id becomes a -run filter.
func runnerTarget(root string, suite *Suite, rel string) []string {
	file := stripNodeID(rel)
	pkg := goPackage(root, suite, file)
	if name := strings.TrimPrefix(rel[len(file):], "::"); name != "" {
		return []string{pkg, "-run", "^" + name + "$"}
	}
	return []string{pkg}
}

// goPackage turns a suite-relative path into the "./..." pattern go test
// accepts. Go tests one package at a time, so a file argument runs the package
// that holds it.
func goPackage(root string, suite *Suite, rel string) string {
	if info, err := os.Stat(filepath.Join(root, suite.Dir, rel)); err == nil && !info.IsDir() {
		rel = filepath.Dir(rel)
	}
	if rel == "." || rel == "" {
		return "./..."
	}
	return "./" + path(rel)
}

// HasTarget reports whether args already name a test target. It takes the
// suite-relative arguments returned by Resolve, where a target always carries a
// path separator or a node id.
//
// Callers need this because go test with no packages tests only the module
// root, so a bare run needs "./..." to cover the whole module — but only when
// the caller has not already picked a target.
func HasTarget(args []string) bool {
	for _, arg := range args {
		if looksLikePath(arg) {
			return true
		}
	}
	return false
}

// relocate rewrites arguments that name an existing path into paths relative
// to the suite's working directory, which is where the runner starts.
// Everything else — flags and their values — passes through untouched.
func relocate(root, cwd string, suite *Suite, args []string) []string {
	out := make([]string, 0, len(args))
	for _, arg := range args {
		out = append(out, relocateArg(root, cwd, suite, arg)...)
	}
	return out
}

func relocateArg(root, cwd string, suite *Suite, arg string) []string {
	if !looksLikePath(arg) {
		return []string{arg}
	}
	repoPath, ok := repoRelative(root, cwd, arg)
	if !ok {
		// The path may still be relative to the suite directory, which is
		// where the runner starts. go test needs a "./" prefix, so shape it
		// here.
		if rel, ok := suiteRelative(root, suite, arg); ok {
			return runnerTarget(root, suite, rel)
		}
		return []string{arg}
	}
	// A path outside this suite is left alone, so the runner reports it
	// rather than us silently pointing somewhere else.
	if !underPrefix(stripNodeID(repoPath), suite.Dir) {
		return []string{arg}
	}
	rel, err := filepath.Rel(suite.Dir, repoPath)
	if err != nil {
		return []string{arg}
	}
	return runnerTarget(root, suite, path(rel))
}

// suiteRelative reports whether arg names a path inside the suite's working
// directory, and returns it relative to that directory. Any node id is kept.
func suiteRelative(root string, suite *Suite, arg string) (string, bool) {
	filePart := stripNodeID(arg)
	if filePart == "" || filepath.IsAbs(filePart) {
		return "", false
	}
	if _, err := os.Stat(filepath.Join(root, suite.Dir, filePart)); err != nil {
		return "", false
	}
	return path(filePart) + arg[len(filePart):], true
}

// suiteForPath returns the suite whose directory is the longest match for a
// repo-relative path. Longest wins so that a suite nested inside another
// resolves to the inner one, whatever the table holds.
func suiteForPath(repoPath string) *Suite {
	matches := make([]*Suite, 0, 2)
	for i := range suites {
		if underPrefix(repoPath, suites[i].Dir) {
			matches = append(matches, &suites[i])
		}
	}
	if len(matches) == 0 {
		return nil
	}
	sort.SliceStable(matches, func(a, b int) bool {
		return len(matches[a].Dir) > len(matches[b].Dir)
	})
	return matches[0]
}

// underPrefix reports whether repoPath is prefix itself or sits below it.
func underPrefix(repoPath, prefix string) bool {
	return repoPath == prefix || strings.HasPrefix(repoPath, prefix+"/")
}

// repoRelative turns a user-supplied path into a slash-separated path relative
// to the git root, reporting false when it does not point at anything real.
// The path is tried against the working directory first, then against the git
// root, so both "internal/testsuite" from inside tools/ods/ and
// "tools/ods/internal/testsuite" from anywhere work.
func repoRelative(root, cwd, arg string) (string, bool) {
	filePart := stripNodeID(arg)
	if filePart == "" {
		return "", false
	}

	candidates := []string{}
	if filepath.IsAbs(filePart) {
		candidates = append(candidates, filePart)
	} else {
		candidates = append(candidates,
			filepath.Join(cwd, filePart),
			filepath.Join(root, filePart),
		)
	}

	for _, candidate := range candidates {
		if _, err := os.Stat(candidate); err != nil {
			continue
		}
		rel, err := filepath.Rel(root, candidate)
		if err != nil || strings.HasPrefix(rel, "..") {
			continue
		}
		// Re-attach the node id, if any, now that the file part is anchored.
		rel = path(rel) + arg[len(filePart):]
		return rel, true
	}
	return "", false
}

// looksLikePath reports whether an argument is shaped like a path worth
// rewriting: it has more than one segment, or carries a node id.
//
// A single bare word is deliberately excluded even when a file by that name
// exists. Such a word is far more often a flag value (`-run TestFoo`) than a
// target, and when it really is a target it is already relative to the
// caller's directory, so rewriting it would only change a path that already
// works.
func looksLikePath(arg string) bool {
	if strings.HasPrefix(arg, "-") {
		return false
	}
	return strings.ContainsAny(arg, `/\`) || strings.Contains(arg, "::")
}

// stripNodeID drops the trailing "::TestName" of a node id, leaving the part
// that exists on disk.
func stripNodeID(arg string) string {
	if idx := strings.Index(arg, "::"); idx >= 0 {
		return arg[:idx]
	}
	return arg
}

// path joins segments and normalizes to forward slashes, which is what both
// go test and the prefix table expect.
func path(segments ...string) string {
	joined := filepath.Join(segments...)
	return filepath.ToSlash(joined)
}
