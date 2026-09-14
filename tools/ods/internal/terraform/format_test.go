package terraform

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFormatFileRewritesUnformattedSource(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "main.tf")
	unformatted := "variable \"name\" {\ntype=string\n  default   = \"onyx\"\n}\n"
	if err := os.WriteFile(path, []byte(unformatted), 0o644); err != nil {
		t.Fatal(err)
	}

	res, err := FormatFile(path, true)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Changed {
		t.Fatal("expected the file to need formatting")
	}

	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	want := "variable \"name\" {\n  type    = string\n  default = \"onyx\"\n}\n"
	if string(got) != want {
		t.Errorf("got:\n%s\nwant:\n%s", got, want)
	}

	// Formatting is idempotent, so a second run reports no change.
	res, err = FormatFile(path, true)
	if err != nil {
		t.Fatal(err)
	}
	if res.Changed {
		t.Error("expected the formatted file to be left alone")
	}
}

func TestFormatFileCheckDoesNotWrite(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "main.tf")
	unformatted := "variable \"name\" {\ntype=string\n}\n"
	if err := os.WriteFile(path, []byte(unformatted), 0o644); err != nil {
		t.Fatal(err)
	}

	res, err := FormatFile(path, false)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Changed {
		t.Fatal("expected the file to need formatting")
	}

	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != unformatted {
		t.Error("--check must not rewrite the file")
	}
}

func TestFormatFileRejectsInvalidHCL(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "broken.tf")
	if err := os.WriteFile(path, []byte("variable \"name\" {\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	if _, err := FormatFile(path, true); err == nil {
		t.Fatal("expected invalid HCL to be reported")
	}
}
