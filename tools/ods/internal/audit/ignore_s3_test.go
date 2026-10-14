package audit

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// assertNoTempAllowlists fails when an ods-audit-ignores temp file is left in dir.
func assertNoTempAllowlists(t *testing.T, dir string) {
	t.Helper()
	leftovers, err := filepath.Glob(filepath.Join(dir, "ods-audit-ignores-*.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(leftovers) != 0 {
		t.Fatalf("expected the temp allowlist to be removed, found %v", leftovers)
	}
}

func TestFetchIgnores_emptyURLHasNoSuppressions(t *testing.T) {
	entries, err := FetchIgnores("")
	if err != nil || entries != nil {
		t.Fatalf("expected no entries and no error, got %v, %v", entries, err)
	}
}

func TestFetchIgnores_invalidS3URLRemovesTheTempFile(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("TMPDIR", tmp)

	_, err := FetchIgnores("s3://onyx-internal-tools")
	if err == nil || err.Error() != "invalid S3 URL: must be s3://bucket/key" {
		t.Fatalf("expected an invalid S3 URL error, got %v", err)
	}
	assertNoTempAllowlists(t, tmp)

	// An S3 fetch failure is never treated as an empty allowlist to edit.
	_, err = LoadIgnoresForEdit("s3://onyx-internal-tools")
	if err == nil || err.Error() != "invalid S3 URL: must be s3://bucket/key" {
		t.Fatalf("expected LoadIgnoresForEdit to return the S3 error, got %v", err)
	}
}

func TestFetchIgnores_malformedLocalFile(t *testing.T) {
	path := writeFixture(t, t.TempDir(), "ignores.json", `{"ignores": [`)

	_, err := FetchIgnores(path)
	if err == nil || !strings.HasPrefix(err.Error(), "failed to parse allowlist "+path+": ") {
		t.Fatalf("expected a parse error naming %s, got %v", path, err)
	}
	// Only a missing file bootstraps an empty allowlist; a corrupt one must not
	// be overwritten by the editor.
	_, err = LoadIgnoresForEdit(path)
	if err == nil || !strings.HasPrefix(err.Error(), "failed to parse allowlist "+path+": ") {
		t.Fatalf("expected LoadIgnoresForEdit to return the parse error, got %v", err)
	}
}

func TestSaveIgnores_uploadsSortedAllowlistToS3(t *testing.T) {
	bin := fakeBinDir(t)
	tmp := t.TempDir()
	t.Setenv("TMPDIR", tmp)
	uploaded := filepath.Join(t.TempDir(), "uploaded.json")
	t.Setenv("FAKE_AWS_UPLOADED", uploaded)
	awsArgs := writeFakeCommand(t, bin, "aws", `cp "$3" "$FAKE_AWS_UPLOADED"`)

	const url = "s3://onyx-internal-tools/audit/ignores.json"
	entries := []IgnoreEntry{
		{ID: "GHSA-zzzz", Reason: "dev only"},
		{ID: "CVE-2026-0001", Ecosystem: "npm", Reason: "not reachable", Expires: "2026-12-31"},
	}
	want := []IgnoreEntry{entries[1], entries[0]}
	if err := SaveIgnores(url, entries); err != nil {
		t.Fatalf("SaveIgnores: %v", err)
	}

	args := awsArgs()
	if len(args) != 1 {
		t.Fatalf("expected one aws call, got %q", args)
	}
	fields := args[0]
	if len(fields) != 4 || fields[0] != "s3" || fields[1] != "cp" || fields[3] != url {
		t.Fatalf("expected %q, got %q", "s3 cp <tmp> "+url, args[0])
	}
	if filepath.Dir(fields[2]) != tmp {
		t.Fatalf("expected the upload source under TMPDIR %q, got %q", tmp, fields[2])
	}
	assertNoTempAllowlists(t, tmp)

	got, err := readIgnoresFile(uploaded)
	if err != nil {
		t.Fatalf("uploaded allowlist: %v", err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("expected the sorted entries %+v, got %+v", want, got)
	}
}

func TestSaveIgnores_failures(t *testing.T) {
	t.Run("upload failure", func(t *testing.T) {
		bin := fakeBinDir(t)
		tmp := t.TempDir()
		t.Setenv("TMPDIR", tmp)
		writeFakeCommand(t, bin, "aws", "exit 255")

		err := SaveIgnores("s3://onyx-internal-tools/audit/ignores.json", []IgnoreEntry{{ID: "GHSA-zzzz"}})
		if err == nil || !strings.HasPrefix(err.Error(), "aws s3 cp failed: exit status 255") {
			t.Fatalf("expected the aws failure, got %v", err)
		}
		assertNoTempAllowlists(t, tmp)
	})

	t.Run("no usable temp directory", func(t *testing.T) {
		t.Setenv("TMPDIR", filepath.Join(t.TempDir(), "missing"))
		const url = "s3://onyx-internal-tools/audit/ignores.json"
		if err := SaveIgnores(url, []IgnoreEntry{{ID: "GHSA-zzzz"}}); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("expected SaveIgnores to fail creating the temp file, got %v", err)
		}
		if _, err := FetchIgnores(url); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("expected FetchIgnores to fail creating the temp file, got %v", err)
		}
	})

	t.Run("local write failure", func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "missing-dir", "ignores.json")
		err := SaveIgnores(path, []IgnoreEntry{{ID: "GHSA-zzzz"}})
		if err == nil || !strings.HasPrefix(err.Error(), "failed to write allowlist "+path+": ") || !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("expected a write error for %s, got %v", path, err)
		}
	})
}
