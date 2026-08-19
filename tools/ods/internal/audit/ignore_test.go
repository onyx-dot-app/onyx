package audit

import (
	"testing"
	"time"
)

func TestApplyIgnores(t *testing.T) {
	now := time.Date(2026, 6, 26, 12, 0, 0, 0, time.UTC)

	findings := []Finding{
		{ID: "GHSA-keep", Ecosystem: "npm", Package: "a", Severity: SeverityCritical},
		{ID: "GHSA-byid", Ecosystem: "npm", Package: "b", Severity: SeverityCritical},
		{ID: "GHSA-byalias", Aliases: []string{"CVE-2026-9"}, Ecosystem: "PyPI", Package: "c", Severity: SeverityHigh},
		{ID: "GHSA-expired", Ecosystem: "npm", Package: "d", Severity: SeverityCritical},
		{ID: "GHSA-future", Ecosystem: "npm", Package: "e", Severity: SeverityCritical},
		{ID: "GHSA-ecomismatch", Ecosystem: "npm", Package: "f", Severity: SeverityCritical},
	}

	ignores := []IgnoreEntry{
		{ID: "GHSA-byid"},
		{ID: "CVE-2026-9"},                          // matches GHSA-byalias via alias
		{ID: "GHSA-expired", Expires: "2026-06-25"}, // yesterday -> expired
		{ID: "GHSA-future", Expires: "2026-12-31"},  // future -> active
		{ID: "GHSA-ecomismatch", Ecosystem: "PyPI"}, // ecosystem mismatch -> no match
		{ID: ""}, // empty id ignored
	}

	kept, suppressed := applyIgnores(findings, ignores, now)

	keptIDs := idSet(kept)
	suppIDs := idSet(suppressed)

	if !suppIDs["GHSA-byid"] {
		t.Error("GHSA-byid should be suppressed by id")
	}
	if !suppIDs["GHSA-byalias"] {
		t.Error("GHSA-byalias should be suppressed by alias")
	}
	if !suppIDs["GHSA-future"] {
		t.Error("GHSA-future (expires in future) should be suppressed")
	}
	if !keptIDs["GHSA-expired"] {
		t.Error("GHSA-expired should NOT be suppressed (past expiry)")
	}
	if !keptIDs["GHSA-ecomismatch"] {
		t.Error("GHSA-ecomismatch should NOT be suppressed (ecosystem mismatch)")
	}
	if !keptIDs["GHSA-keep"] {
		t.Error("GHSA-keep should remain")
	}

	if len(kept)+len(suppressed) != len(findings) {
		t.Errorf("kept(%d)+suppressed(%d) != findings(%d)", len(kept), len(suppressed), len(findings))
	}
}

func TestEntryExpiredInclusiveBoundary(t *testing.T) {
	entry := &IgnoreEntry{ID: "x", Expires: "2026-06-26"}

	// Same day, still valid (inclusive).
	if entryExpired(entry, time.Date(2026, 6, 26, 23, 59, 0, 0, time.UTC)) {
		t.Error("entry should be valid through the end of the expires day")
	}
	// Next day, expired.
	if !entryExpired(entry, time.Date(2026, 6, 27, 0, 0, 1, 0, time.UTC)) {
		t.Error("entry should be expired the day after expires")
	}
	// No expiry -> never expires.
	if entryExpired(&IgnoreEntry{ID: "x"}, time.Now()) {
		t.Error("entry with no expiry should never expire")
	}
	// Malformed date -> treated as non-expiring (still suppresses).
	if entryExpired(&IgnoreEntry{ID: "x", Expires: "not-a-date"}, time.Now()) {
		t.Error("malformed expiry should be treated as non-expiring")
	}
}

func idSet(findings []Finding) map[string]bool {
	m := make(map[string]bool, len(findings))
	for _, f := range findings {
		m[f.ID] = true
	}
	return m
}
