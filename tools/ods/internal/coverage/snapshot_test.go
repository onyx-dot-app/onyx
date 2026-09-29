package coverage

import (
	"bytes"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// testCommit is a full object name whose short form is "abc1234".
const testCommit = "abc1234" + "000000000000000000000000000000000"

func TestNewSnapshot_recordsExactCounts(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {2, 3}})

	snapshot := NewSnapshot(profile, testCommit, "tools/ods")

	want := SnapshotPackage{Covered: 2, Statements: 3}
	if got := snapshot.Packages["cmd"]; got != want {
		t.Fatalf("expected the counts kept exactly, got %+v", got)
	}
	if snapshot.Version != SnapshotVersion || snapshot.Commit != testCommit || snapshot.Module != "tools/ods" {
		t.Fatalf("unexpected snapshot identity: %+v", snapshot)
	}
}

func TestSnapshot_encodeParseRoundTrip(t *testing.T) {
	snapshot := NewSnapshot(profileOf(map[string][2]int{"cmd": {2, 3}, "internal/audit": {0, 4}}), testCommit, "tools/ods")

	encoded, err := snapshot.Encode()
	if err != nil {
		t.Fatalf("failed to encode the snapshot: %v", err)
	}
	if !strings.HasPrefix(string(encoded), "#") {
		t.Fatalf("expected the explanatory header first:\n%s", encoded)
	}

	again, err := snapshot.Encode()
	if err != nil {
		t.Fatalf("failed to encode the snapshot again: %v", err)
	}
	if !bytes.Equal(encoded, again) {
		t.Fatalf("expected a deterministic encoding:\n%s\n---\n%s", encoded, again)
	}

	parsed, err := ParseSnapshot(encoded)
	if err != nil {
		t.Fatalf("failed to parse the snapshot: %v", err)
	}
	if !reflect.DeepEqual(parsed, snapshot) {
		t.Fatalf("round trip changed the snapshot:\ngot  %+v\nwant %+v", parsed, snapshot)
	}
}

func TestSnapshot_ProfileRebuildsTheSourceProfile(t *testing.T) {
	profile := profileOf(map[string][2]int{"internal/audit": {0, 4}, "cmd": {2, 3}})
	snapshot := NewSnapshot(profile, testCommit, "tools/ods")

	want := &Profile{Packages: []PackageCoverage{
		{Package: "cmd", Covered: 2, Total: 3},
		{Package: "internal/audit", Covered: 0, Total: 4},
	}}
	if got := snapshot.Profile(); !reflect.DeepEqual(got, want) {
		t.Fatalf("expected the source profile back, got %+v", got)
	}
}

// A snapshot holds counts, so its percentages are exact rather than rounded
// down the way a floor is.
func TestSnapshot_ReferenceIsBaseKindWithUnflooredPercents(t *testing.T) {
	snapshot := NewSnapshot(profileOf(map[string][2]int{"cmd": {2, 3}}), testCommit, "tools/ods")

	reference := snapshot.Reference()

	if reference.Kind != ReferenceBase {
		t.Fatalf("expected a base reference, got %q", reference.Kind)
	}
	if reference.Label != "abc1234" {
		t.Fatalf("expected the short commit as the label, got %q", reference.Label)
	}
	if got := reference.Packages["cmd"]; got <= 66.6 || got >= 66.7 {
		t.Fatalf("expected the exact percentage, got %v", got)
	}
	if got := reference.Total; got <= 66.6 || got >= 66.7 {
		t.Fatalf("expected the exact total, got %v", got)
	}
}

func TestParseSnapshot_rejectsBrokenSnapshots(t *testing.T) {
	valid := `version: 1
commit: ` + testCommit + `
module: tools/ods
packages:
  cmd:
    covered: 2
    statements: 3
`
	if _, err := ParseSnapshot([]byte(valid)); err != nil {
		t.Fatalf("expected the valid snapshot accepted: %v", err)
	}

	cases := map[string]string{
		"malformed yaml":      "version: 1\n  commit: bad\n:\n",
		"unknown field":       strings.Replace(valid, "module:", "extra: 1\nmodule:", 1),
		"covered above total": strings.Replace(valid, "covered: 2", "covered: 4", 1),
		"negative count":      strings.Replace(valid, "covered: 2", "covered: -1", 1),
		"short commit":        strings.Replace(valid, testCommit, "abc1234", 1),
		"non-hex commit":      strings.Replace(valid, testCommit, strings.Repeat("z", 40), 1),
		"empty module":        strings.Replace(valid, "module: tools/ods", `module: ""`, 1),
		"wrong version":       strings.Replace(valid, "version: 1", "version: 2", 1),
		"empty package name":  strings.Replace(valid, "  cmd:", `  "":`, 1),
	}
	for name, data := range cases {
		if _, err := ParseSnapshot([]byte(data)); err == nil {
			t.Errorf("%s: expected the snapshot rejected", name)
		}
	}
}

func TestSnapshotObjectKey(t *testing.T) {
	want := "coverage/tools-ods/" + testCommit + ".yaml"
	if got := SnapshotObjectKey("tools/ods", testCommit); got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestShortCommit(t *testing.T) {
	if got := ShortCommit(testCommit); got != "abc1234" {
		t.Fatalf("got %q, want %q", got, "abc1234")
	}
	if got := ShortCommit("abc"); got != "abc" {
		t.Fatalf("expected a short input returned whole, got %q", got)
	}
}

func TestSnapshot_saveAndLoadFile(t *testing.T) {
	snapshot := NewSnapshot(profileOf(map[string][2]int{"cmd": {2, 3}}), testCommit, "tools/ods")
	path := filepath.Join(t.TempDir(), "snapshot.yaml")

	if err := snapshot.SaveFile(path); err != nil {
		t.Fatalf("failed to save the snapshot: %v", err)
	}
	loaded, err := LoadSnapshotFile(path)
	if err != nil {
		t.Fatalf("failed to load the snapshot: %v", err)
	}
	if !reflect.DeepEqual(loaded, snapshot) {
		t.Fatalf("got %+v, want %+v", loaded, snapshot)
	}
}

// A snapshot that is missing, or that the reader cannot trust, must fail
// loudly rather than compare against nothing.
func TestLoadSnapshotFile_rejectsMissingAndBrokenFiles(t *testing.T) {
	dir := t.TempDir()

	if _, err := LoadSnapshotFile(filepath.Join(dir, "absent.yaml")); err == nil {
		t.Fatalf("expected a missing snapshot rejected")
	}

	broken := filepath.Join(dir, "broken.yaml")
	if err := os.WriteFile(broken, []byte("version: 9\n"), 0644); err != nil {
		t.Fatalf("failed to write the broken snapshot: %v", err)
	}
	if _, err := LoadSnapshotFile(broken); err == nil {
		t.Fatalf("expected a broken snapshot rejected")
	}
}
