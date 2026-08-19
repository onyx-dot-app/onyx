package audit

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/s3"
)

// DefaultIgnoreURL is the S3 location of the audit allowlist. It is fetched at
// runtime so suppressions can be added/removed without a code change.
const DefaultIgnoreURL = "s3://onyx-internal-tools/audit/ignores.json"

// expiresLayout is the date format for IgnoreEntry.Expires (inclusive last day).
const expiresLayout = "2006-01-02"

// IgnoreEntry is a single suppressed advisory in the allowlist.
type IgnoreEntry struct {
	// ID matches a finding's id or any of its aliases (case-insensitive).
	ID string `json:"id"`
	// Ecosystem, when set, restricts the suppression to that ecosystem.
	Ecosystem string `json:"ecosystem,omitempty"`
	Reason    string `json:"reason,omitempty"`
	AddedBy   string `json:"added_by,omitempty"`
	// Expires is an inclusive YYYY-MM-DD date; empty means it never expires.
	Expires string `json:"expires,omitempty"`
}

type ignoreFile struct {
	Ignores []IgnoreEntry `json:"ignores"`
}

// FetchIgnores downloads and parses the allowlist from an s3:// URL. A plain
// local path (no s3:// prefix) is read directly from disk; a missing file is an
// error, so a typo'd --ignore-url surfaces rather than silently yielding no
// suppressions. An empty URL yields an empty list.
func FetchIgnores(url string) ([]IgnoreEntry, error) {
	if url == "" {
		return nil, nil
	}

	if !strings.HasPrefix(url, "s3://") {
		return readIgnoresFile(url)
	}

	tmp, err := os.CreateTemp("", "ods-audit-ignores-*.json")
	if err != nil {
		return nil, err
	}
	tmpPath := tmp.Name()
	_ = tmp.Close()
	defer func() { _ = os.Remove(tmpPath) }()

	if err := s3.FetchToFile(url, tmpPath); err != nil {
		return nil, err
	}
	return readIgnoresFile(tmpPath)
}

// readIgnoresFile reads and parses an allowlist from a local file. A missing
// file returns an os.ErrNotExist error; callers that want to bootstrap an empty
// allowlist (e.g. the editor) should use LoadIgnoresForEdit.
func readIgnoresFile(path string) ([]IgnoreEntry, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var f ignoreFile
	if err := json.Unmarshal(data, &f); err != nil {
		return nil, fmt.Errorf("failed to parse allowlist %s: %w", path, err)
	}
	return f.Ignores, nil
}

// applyIgnores splits findings into kept and suppressed based on the allowlist,
// evaluating expiry against now.
func applyIgnores(findings []Finding, ignores []IgnoreEntry, now time.Time) (kept, suppressed []Finding) {
	for _, f := range findings {
		if entry := matchIgnore(f, ignores, now); entry != nil {
			log.Debugf("Suppressing %s (%s) via allowlist: %s", f.ID, f.Package, entry.Reason)
			suppressed = append(suppressed, f)
		} else {
			kept = append(kept, f)
		}
	}
	return kept, suppressed
}

// matchIgnore returns the allowlist entry that suppresses f, or nil. An entry
// matches when its id equals the finding id or one of its aliases (and, if set,
// its ecosystem matches). Expired entries never match.
func matchIgnore(f Finding, ignores []IgnoreEntry, now time.Time) *IgnoreEntry {
	for i := range ignores {
		entry := &ignores[i]
		if entry.ID == "" {
			continue
		}
		if entryExpired(entry, now) {
			log.Debugf("Allowlist entry for %s expired on %s; not suppressing", entry.ID, entry.Expires)
			continue
		}
		if entry.Ecosystem != "" && !strings.EqualFold(entry.Ecosystem, f.Ecosystem) {
			continue
		}
		if idMatches(entry.ID, f) {
			return entry
		}
	}
	return nil
}

// entryExpired reports whether the entry's inclusive expiry date has passed.
func entryExpired(entry *IgnoreEntry, now time.Time) bool {
	if entry.Expires == "" {
		return false
	}
	exp, err := time.Parse(expiresLayout, entry.Expires)
	if err != nil {
		// A malformed date is treated as non-expiring; the entry still suppresses.
		log.Warnf("Allowlist entry for %s has invalid expires %q: %v", entry.ID, entry.Expires, err)
		return false
	}
	// Valid through the end of the Expires day; expired once now reaches the
	// following day.
	return !now.Before(exp.AddDate(0, 0, 1))
}

func idMatches(id string, f Finding) bool {
	if strings.EqualFold(id, f.ID) {
		return true
	}
	for _, alias := range f.Aliases {
		if strings.EqualFold(id, alias) {
			return true
		}
	}
	return false
}
