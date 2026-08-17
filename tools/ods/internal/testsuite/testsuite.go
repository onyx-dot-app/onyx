// Package testsuite maps a suite name or a file path onto the test runner that
// knows how to execute it. The repo has four runners (pytest, jest for web,
// jest for mobile, playwright) with different working directories and
// arguments; this package holds the routing table and the pure logic that
// picks an entry from it.
package testsuite

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Runner identifies the tool that executes a suite.
type Runner string

const (
	RunnerPytest     Runner = "pytest"
	RunnerJest       Runner = "jest"
	RunnerPlaywright Runner = "playwright"
)

// ErrNoArgs is returned when no suite or path was given.
var ErrNoArgs = errors.New("no suite or path given")

// Suite describes one test suite and how to run it.
type Suite struct {
	// Name is the canonical name accepted on the command line.
	Name string
	// Aliases are alternate names accepted on the command line.
	Aliases []string
	// Runner is the tool that executes this suite.
	Runner Runner
	// Dir is the working directory for the runner, relative to the git root.
	Dir string
	// Target is the suite's root test path, relative to Dir. It doubles as
	// the default argument for pytest and as the prefix used to infer the
	// suite from a path.
	Target string
	// NeedsBackendEnv marks suites that need credentials from .vscode/.env.
	NeedsBackendEnv bool
	// DefaultArgs are passed to the runner before any user arguments, so a
	// user argument for the same option still wins.
	DefaultArgs []string
	// Short is the one-line description shown in help output.
	Short string
}

// Prefix returns the suite's test path relative to the git root.
func (s *Suite) Prefix() string {
	return path(s.Dir, s.Target)
}

// suites is the routing table. Order here is the order shown in help.
var suites = []Suite{
	{
		Name:    "unit",
		Aliases: []string{"u"},
		Runner:  RunnerPytest,
		Dir:     "backend",
		Target:  "tests/unit",
		Short:   "Backend unit tests (no services needed)",
	},
	{
		Name:            "external",
		Aliases:         []string{"edu", "ext"},
		Runner:          RunnerPytest,
		Dir:             "backend",
		Target:          "tests/external_dependency_unit",
		NeedsBackendEnv: true,
		// Match CI, which leaves nightly-only tests to the nightly workflow.
		DefaultArgs: []string{"-m", "not nightly"},
		Short:       "External dependency unit tests (needs Postgres, Redis, OpenSearch, MinIO)",
	},
	{
		Name:            "integration",
		Aliases:         []string{"int"},
		Runner:          RunnerPytest,
		Dir:             "backend",
		Target:          "tests/integration",
		NeedsBackendEnv: true,
		Short:           "Backend integration tests (needs a full Onyx deployment)",
	},
	{
		Name:    "web",
		Aliases: []string{"jest"},
		Runner:  RunnerJest,
		Dir:     "web",
		Short:   "Web unit and component tests (jest)",
	},
	{
		Name:    "e2e",
		Aliases: []string{"playwright", "pw"},
		Runner:  RunnerPlaywright,
		Dir:     "web",
		Target:  "tests/e2e",
		Short:   "Web end-to-end tests (needs a full Onyx deployment)",
	},
	{
		Name:   "mobile",
		Runner: RunnerJest,
		Dir:    "mobile",
		Short:  "Mobile tests (jest-expo)",
	},
	{
		Name:            "backend",
		Aliases:         []string{"py"},
		Runner:          RunnerPytest,
		Dir:             "backend",
		Target:          "tests",
		NeedsBackendEnv: true,
		Short:           "Any other backend/tests path (daily, regression, api, ...)",
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
// typed relative to it (for example inside backend/) resolves correctly.
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
	return suite, append([]string{path(target)}, rest...), nil
}

// relocate rewrites arguments that name an existing path into paths relative
// to the suite's working directory, which is where the runner starts.
// Everything else — flags, their values, playwright test-name filters — passes
// through untouched.
func relocate(root, cwd string, suite *Suite, args []string) []string {
	out := make([]string, 0, len(args))
	for _, arg := range args {
		out = append(out, relocateArg(root, cwd, suite, arg))
	}
	return out
}

func relocateArg(root, cwd string, suite *Suite, arg string) string {
	if !looksLikePath(arg) {
		return arg
	}
	repoPath, ok := repoRelative(root, cwd, arg)
	if !ok {
		return arg
	}
	// A path outside this suite is left alone, so the runner reports it
	// rather than us silently pointing somewhere else.
	if !underPrefix(stripNodeID(repoPath), suite.Dir) {
		return arg
	}
	rel, err := filepath.Rel(suite.Dir, repoPath)
	if err != nil {
		return arg
	}
	return path(rel)
}

// suiteForPath returns the suite whose prefix is the longest match for a
// repo-relative path. Longest wins so that web/tests/e2e resolves to the e2e
// suite rather than to web.
func suiteForPath(repoPath string) *Suite {
	matches := make([]*Suite, 0, 2)
	for i := range suites {
		if underPrefix(repoPath, suites[i].Prefix()) {
			matches = append(matches, &suites[i])
		}
	}
	if len(matches) == 0 {
		return nil
	}
	sort.SliceStable(matches, func(a, b int) bool {
		return len(matches[a].Prefix()) > len(matches[b].Prefix())
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
// root, so both "tests/unit" from inside backend/ and "backend/tests/unit"
// from anywhere work.
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
// rewriting: it has more than one segment, or carries a pytest node id.
//
// A single bare word is deliberately excluded even when a file by that name
// exists. Such a word is far more often a flag value (`-k web`, a playwright
// test-name filter) than a target, and when it really is a target it is
// already relative to the caller's directory, so rewriting it would only
// change a path that already works.
func looksLikePath(arg string) bool {
	if strings.HasPrefix(arg, "-") {
		return false
	}
	return strings.ContainsAny(arg, `/\`) || strings.Contains(arg, "::")
}

// stripNodeID drops the trailing "::test_name" of a pytest node id, leaving
// the part that exists on disk.
func stripNodeID(arg string) string {
	if idx := strings.Index(arg, "::"); idx >= 0 {
		return arg[:idx]
	}
	return arg
}

// path joins segments and normalizes to forward slashes, which is what both
// the runners and the prefix table expect.
func path(segments ...string) string {
	joined := filepath.Join(segments...)
	return filepath.ToSlash(joined)
}
