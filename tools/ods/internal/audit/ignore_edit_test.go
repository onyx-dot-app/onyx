package audit

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestMarshalIgnoresRoundTrip(t *testing.T) {
	entries := []IgnoreEntry{
		{ID: "GHSA-aaaa", Ecosystem: "npm", Reason: "not reachable", AddedBy: "you@onyx.app", Expires: "2026-09-01"},
		{ID: "GHSA-bbbb"},
	}

	data, err := MarshalIgnores(entries)
	if err != nil {
		t.Fatalf("MarshalIgnores: %v", err)
	}

	var f ignoreFile
	if err := json.Unmarshal(data, &f); err != nil {
		t.Fatalf("Unmarshal: %v", err)
	}
	if !reflect.DeepEqual(f.Ignores, entries) {
		t.Fatalf("round trip mismatch:\n got %#v\nwant %#v", f.Ignores, entries)
	}
}

func TestMarshalIgnoresOmitsEmptyFields(t *testing.T) {
	data, err := MarshalIgnores([]IgnoreEntry{{ID: "GHSA-only"}})
	if err != nil {
		t.Fatalf("MarshalIgnores: %v", err)
	}
	for _, field := range []string{"ecosystem", "reason", "added_by", "expires"} {
		if strings.Contains(string(data), field) {
			t.Errorf("expected %q to be omitted, got:\n%s", field, data)
		}
	}
}

func TestValidateEntry(t *testing.T) {
	tests := []struct {
		name    string
		entry   IgnoreEntry
		wantErr bool
	}{
		{"ok minimal", IgnoreEntry{ID: "GHSA-x"}, false},
		{"ok full", IgnoreEntry{ID: "GHSA-x", Expires: "2026-01-02"}, false},
		{"empty id", IgnoreEntry{ID: "   "}, true},
		{"bad expires", IgnoreEntry{ID: "GHSA-x", Expires: "09/01/2026"}, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := ValidateEntry(tt.entry)
			if (err != nil) != tt.wantErr {
				t.Fatalf("ValidateEntry(%+v) err = %v, wantErr = %v", tt.entry, err, tt.wantErr)
			}
		})
	}
}

func TestValidateExpires(t *testing.T) {
	if err := ValidateExpires(""); err != nil {
		t.Errorf("empty expires should be valid, got %v", err)
	}
	if err := ValidateExpires("2026-09-01"); err != nil {
		t.Errorf("valid expires rejected: %v", err)
	}
	if err := ValidateExpires("not-a-date"); err == nil {
		t.Errorf("invalid expires accepted")
	}
}

func TestSortIgnores(t *testing.T) {
	entries := []IgnoreEntry{
		{ID: "GHSA-b", Ecosystem: "pypi"},
		{ID: "GHSA-a", Ecosystem: "npm"},
		{ID: "GHSA-a", Ecosystem: "go"},
	}
	SortIgnores(entries)
	got := []string{}
	for _, e := range entries {
		got = append(got, e.ID+"/"+e.Ecosystem)
	}
	want := []string{"GHSA-a/go", "GHSA-a/npm", "GHSA-b/pypi"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("SortIgnores order = %v, want %v", got, want)
	}
}

func TestDiffIgnores(t *testing.T) {
	oldEntries := []IgnoreEntry{
		{ID: "A"},
		{ID: "B", Reason: "old"},
		{ID: "C"},
	}
	newEntries := []IgnoreEntry{
		{ID: "A"},
		{ID: "B", Reason: "new"},
		{ID: "D"},
	}
	added, removed, changed := DiffIgnores(oldEntries, newEntries)

	if len(added) != 1 || added[0].ID != "D" {
		t.Errorf("added = %+v, want [D]", added)
	}
	if len(removed) != 1 || removed[0].ID != "C" {
		t.Errorf("removed = %+v, want [C]", removed)
	}
	if len(changed) != 1 || changed[0].ID != "B" || changed[0].Reason != "new" {
		t.Errorf("changed = %+v, want [B reason=new]", changed)
	}
}

func TestSaveIgnoresLocalRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "ignores.json")
	entries := []IgnoreEntry{
		{ID: "GHSA-bbbb", Ecosystem: "pypi"},
		{ID: "GHSA-aaaa", Ecosystem: "npm", Reason: "accepted"},
	}

	if err := SaveIgnores(path, entries); err != nil {
		t.Fatalf("SaveIgnores: %v", err)
	}

	got, err := FetchIgnores(path)
	if err != nil {
		t.Fatalf("FetchIgnores: %v", err)
	}

	// SaveIgnores sorts before writing, so the read-back order is deterministic.
	want := []IgnoreEntry{
		{ID: "GHSA-aaaa", Ecosystem: "npm", Reason: "accepted"},
		{ID: "GHSA-bbbb", Ecosystem: "pypi"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("read back = %#v, want %#v", got, want)
	}
}

func TestSaveIgnoresRejectsInvalid(t *testing.T) {
	path := filepath.Join(t.TempDir(), "ignores.json")
	err := SaveIgnores(path, []IgnoreEntry{{ID: ""}})
	if err == nil {
		t.Fatal("expected SaveIgnores to reject an entry with empty id")
	}
}

func TestSaveIgnoresRejectsDuplicates(t *testing.T) {
	path := filepath.Join(t.TempDir(), "ignores.json")
	err := SaveIgnores(path, []IgnoreEntry{
		{ID: "GHSA-x", Ecosystem: "npm"},
		{ID: "ghsa-x", Ecosystem: "NPM", Reason: "dup, case-insensitive"},
	})
	if err == nil {
		t.Fatal("expected SaveIgnores to reject duplicate id+ecosystem entries")
	}
}

func TestDuplicateKeys(t *testing.T) {
	dups := DuplicateKeys([]IgnoreEntry{
		{ID: "GHSA-a", Ecosystem: "npm"},
		{ID: "GHSA-a", Ecosystem: "pypi"}, // distinct ecosystem, not a dup
		{ID: "GHSA-a", Ecosystem: "npm"},  // dup of the first
		{ID: "GHSA-b"},
	})
	if len(dups) != 1 {
		t.Fatalf("expected 1 duplicate key, got %v", dups)
	}
}

func TestFetchIgnoresMissingLocalFileErrors(t *testing.T) {
	path := filepath.Join(t.TempDir(), "does-not-exist.json")
	if _, err := FetchIgnores(path); err == nil {
		t.Fatal("expected FetchIgnores to error on a missing local file")
	} else if !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("expected os.ErrNotExist, got %v", err)
	}
}

func TestLoadIgnoresForEditMissingLocalFileBootstraps(t *testing.T) {
	path := filepath.Join(t.TempDir(), "does-not-exist.json")
	got, err := LoadIgnoresForEdit(path)
	if err != nil {
		t.Fatalf("LoadIgnoresForEdit on missing local file should not error, got %v", err)
	}
	if got != nil {
		t.Fatalf("expected nil entries for missing file, got %#v", got)
	}
}
