// Package version provides semver parsing and compatibility checks.
package version

import (
	"strconv"
	"strings"
)

// Semver holds parsed semantic version components.
type Semver struct {
	Major int
	Minor int
	Patch int
}

// MinServer is the minimum backend version required by this CLI.
var MinServer = Semver{Major: 3, Minor: 0, Patch: 0}

// Parse extracts major, minor, patch from a version string like "3.1.2" or "v3.1.2".
// Returns ok=false if the string is not valid semver.
func Parse(v string) (Semver, bool) {
	v = strings.TrimPrefix(v, "v")
	// Strip any pre-release suffix (e.g. "-beta.1") and build metadata (e.g. "+build.1")
	if idx := strings.IndexAny(v, "-+"); idx != -1 {
		v = v[:idx]
	}
	parts := strings.SplitN(v, ".", 3)
	if len(parts) != 3 {
		return Semver{}, false
	}
	major, err := strconv.Atoi(parts[0])
	if err != nil {
		return Semver{}, false
	}
	minor, err := strconv.Atoi(parts[1])
	if err != nil {
		return Semver{}, false
	}
	patch, err := strconv.Atoi(parts[2])
	if err != nil {
		return Semver{}, false
	}
	return Semver{Major: major, Minor: minor, Patch: patch}, true
}

// LessThan reports whether s is strictly less than other.
func (s Semver) LessThan(other Semver) bool {
	if s.Major != other.Major {
		return s.Major < other.Major
	}
	if s.Minor != other.Minor {
		return s.Minor < other.Minor
	}
	return s.Patch < other.Patch
}
