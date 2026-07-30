// Package version provides small helpers for normalizing and comparing
// semver-ish version strings (release tags, advisory bounds, etc.).
package version

import (
	"strings"

	"github.com/google/osv-scalibr/semantic"
)

// Normalize strips a leading "v" so tag names (v6.0.2) and bare versions (6.0.2)
// compare on equal footing, and trims surrounding whitespace.
func Normalize(s string) string {
	s = strings.TrimSpace(s)
	if len(s) > 1 && (s[0] == 'v' || s[0] == 'V') {
		s = s[1:]
	}
	return s
}

// IsSemverish reports whether s looks like a numeric version once normalized,
// filtering out branch names and floating tags that can't be ordered.
func IsSemverish(s string) bool {
	s = Normalize(s)
	return s != "" && s[0] >= '0' && s[0] <= '9'
}

// Compare orders two semver-ish strings via osv-scalibr's comparator (the same
// one used for npm/Go/crates OSV matching). Inputs are normalized first. It
// returns -1, 0, or 1 for a < b, a == b, a > b.
func Compare(a, b string) int {
	c, _ := semantic.ParseSemverVersion(Normalize(a)).CompareStr(Normalize(b))
	return c
}
