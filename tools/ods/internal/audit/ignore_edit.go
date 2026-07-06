package audit

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/s3"
)

// MarshalIgnores serializes entries as the on-disk allowlist JSON document.
func MarshalIgnores(entries []IgnoreEntry) ([]byte, error) {
	return json.MarshalIndent(ignoreFile{Ignores: entries}, "", "  ")
}

// ValidateEntry checks a single allowlist entry: id is required and expires,
// when set, must be a YYYY-MM-DD date.
func ValidateEntry(e IgnoreEntry) error {
	if strings.TrimSpace(e.ID) == "" {
		return fmt.Errorf("id is required")
	}
	if err := ValidateExpires(e.Expires); err != nil {
		return err
	}
	return nil
}

// ValidateExpires reports whether a non-empty expires value is a YYYY-MM-DD
// date. An empty value (never expires) is valid.
func ValidateExpires(s string) error {
	if s == "" {
		return nil
	}
	if _, err := time.Parse(expiresLayout, s); err != nil {
		return fmt.Errorf("must be YYYY-MM-DD")
	}
	return nil
}

// SortIgnores orders entries by id then ecosystem (case-insensitive) for stable,
// diff-friendly output.
func SortIgnores(entries []IgnoreEntry) {
	sort.SliceStable(entries, func(i, j int) bool {
		a, b := entries[i], entries[j]
		if !strings.EqualFold(a.ID, b.ID) {
			return strings.ToLower(a.ID) < strings.ToLower(b.ID)
		}
		return strings.ToLower(a.Ecosystem) < strings.ToLower(b.Ecosystem)
	})
}

// DiffIgnores compares two allowlists keyed by id+ecosystem and returns the
// entries added, removed, and changed (same key, other fields differ).
func DiffIgnores(oldEntries, newEntries []IgnoreEntry) (added, removed, changed []IgnoreEntry) {
	oldByKey := make(map[string]IgnoreEntry, len(oldEntries))
	for _, e := range oldEntries {
		oldByKey[ignoreKey(e)] = e
	}
	newByKey := make(map[string]IgnoreEntry, len(newEntries))
	for _, e := range newEntries {
		newByKey[ignoreKey(e)] = e
	}
	for _, e := range newEntries {
		if prev, ok := oldByKey[ignoreKey(e)]; !ok {
			added = append(added, e)
		} else if prev != e {
			changed = append(changed, e)
		}
	}
	for _, e := range oldEntries {
		if _, ok := newByKey[ignoreKey(e)]; !ok {
			removed = append(removed, e)
		}
	}
	return added, removed, changed
}

func ignoreKey(e IgnoreEntry) string {
	return strings.ToLower(e.ID) + "\x00" + strings.ToLower(e.Ecosystem)
}

// SaveIgnores validates, sorts, and writes the allowlist. An s3:// URL is
// uploaded via the AWS CLI; a plain local path is written directly to disk.
func SaveIgnores(url string, entries []IgnoreEntry) error {
	for _, e := range entries {
		if err := ValidateEntry(e); err != nil {
			return fmt.Errorf("invalid allowlist entry %q: %w", e.ID, err)
		}
	}
	SortIgnores(entries)

	data, err := MarshalIgnores(entries)
	if err != nil {
		return fmt.Errorf("failed to marshal allowlist: %w", err)
	}

	if !strings.HasPrefix(url, "s3://") {
		if err := os.WriteFile(url, data, 0644); err != nil {
			return fmt.Errorf("failed to write allowlist %s: %w", url, err)
		}
		return nil
	}

	tmp, err := os.CreateTemp("", "ods-audit-ignores-*.json")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer func() { _ = os.Remove(tmpPath) }()
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}

	return s3.PutFile(tmpPath, url)
}
