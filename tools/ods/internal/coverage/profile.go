// Package coverage measures Go statement coverage per package and compares it
// against a committed baseline, so test coverage can only go up.
package coverage

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"path"
	"sort"
	"strconv"
	"strings"
)

// PackageCoverage holds the statement counts for one package.
type PackageCoverage struct {
	// Package is the package path relative to the module root, e.g.
	// "internal/audit". The module root itself is ".".
	Package string
	// Covered is the number of statements run at least once.
	Covered int
	// Total is the number of statements in the package.
	Total int
}

// Percent returns the covered fraction as a percentage. A package with no
// statements counts as fully covered, matching `go tool cover`.
func (p PackageCoverage) Percent() float64 {
	if p.Total == 0 {
		return 100
	}
	return float64(p.Covered) / float64(p.Total) * 100
}

// Profile is the parsed result of a `go test -coverprofile` run.
type Profile struct {
	// Packages is sorted by package path.
	Packages []PackageCoverage
}

// Total returns the coverage percentage across every package.
func (p Profile) Total() float64 {
	var covered, total int
	for _, pkg := range p.Packages {
		covered += pkg.Covered
		total += pkg.Total
	}
	if total == 0 {
		return 100
	}
	return float64(covered) / float64(total) * 100
}

// block identifies one coverage block. The same block can appear more than once
// in a profile, so blocks are merged by this key before counting.
type block struct {
	pkg  string
	span string
}

// ParseProfile reads a coverage profile and aggregates it per package. Package
// paths are made relative to modulePath.
//
// Profile lines look like:
//
//	example.com/m/internal/audit/osv.go:25.64,27.42 2 0
//
// which is <file>:<startLine>.<startCol>,<endLine>.<endCol> <statements> <count>.
func ParseProfile(r io.Reader, modulePath string) (*Profile, error) {
	counts := make(map[block]int)
	stmts := make(map[block]int)

	scanner := bufio.NewScanner(r)
	// Coverage lines are short, but raise the limit so a long import path
	// cannot truncate a profile into a wrong number.
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)

	for lineNo := 1; scanner.Scan(); lineNo++ {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "mode:") {
			continue
		}

		b, numStmts, count, err := parseProfileLine(line, modulePath)
		if err != nil {
			return nil, fmt.Errorf("line %d: %w", lineNo, err)
		}

		stmts[b] = numStmts
		counts[b] += count
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read coverage profile: %w", err)
	}

	byPkg := make(map[string]*PackageCoverage)
	for b, numStmts := range stmts {
		pkg, ok := byPkg[b.pkg]
		if !ok {
			pkg = &PackageCoverage{Package: b.pkg}
			byPkg[b.pkg] = pkg
		}
		pkg.Total += numStmts
		if counts[b] > 0 {
			pkg.Covered += numStmts
		}
	}

	profile := &Profile{Packages: make([]PackageCoverage, 0, len(byPkg))}
	for _, pkg := range byPkg {
		profile.Packages = append(profile.Packages, *pkg)
	}
	sort.Slice(profile.Packages, func(i, j int) bool {
		return profile.Packages[i].Package < profile.Packages[j].Package
	})
	return profile, nil
}

// ParseProfileFile parses the coverage profile at the given path.
func ParseProfileFile(profilePath, modulePath string) (*Profile, error) {
	f, err := os.Open(profilePath)
	if err != nil {
		return nil, fmt.Errorf("open coverage profile: %w", err)
	}
	defer func() { _ = f.Close() }()
	return ParseProfile(f, modulePath)
}

func parseProfileLine(line, modulePath string) (block, int, int, error) {
	fields := strings.Fields(line)
	if len(fields) != 3 {
		return block{}, 0, 0, fmt.Errorf("expected 3 fields, got %d: %q", len(fields), line)
	}

	sep := strings.LastIndex(fields[0], ":")
	if sep < 0 {
		return block{}, 0, 0, fmt.Errorf("missing block position: %q", line)
	}

	numStmts, err := strconv.Atoi(fields[1])
	if err != nil {
		return block{}, 0, 0, fmt.Errorf("invalid statement count: %q", line)
	}
	count, err := strconv.Atoi(fields[2])
	if err != nil {
		return block{}, 0, 0, fmt.Errorf("invalid execution count: %q", line)
	}

	file := fields[0][:sep]
	return block{
		pkg:  relativePackage(path.Dir(file), modulePath),
		span: fields[0],
	}, numStmts, count, nil
}

// relativePackage converts a full import path into a path relative to the
// module root. Paths outside the module are returned unchanged.
func relativePackage(importPath, modulePath string) string {
	if modulePath == "" || importPath == modulePath {
		if importPath == modulePath {
			return "."
		}
		return importPath
	}
	if rel, ok := strings.CutPrefix(importPath, modulePath+"/"); ok {
		return rel
	}
	return importPath
}
