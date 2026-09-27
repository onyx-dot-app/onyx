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

// Results and errors line up with the input files, whatever order the
// concurrent workers finish in.
func TestFormatFilesKeepsInputOrder(t *testing.T) {
	dir := t.TempDir()
	files := map[string]string{
		"clean.tf":   "a = 1\n",
		"messy.tf":   "a=1\n",
		"invalid.tf": "variable \"x\" {\n",
	}
	for name, src := range files {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(src), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	paths := []string{
		filepath.Join(dir, "messy.tf"),
		filepath.Join(dir, "missing.tf"),
		filepath.Join(dir, "clean.tf"),
		filepath.Join(dir, "invalid.tf"),
	}

	results, errs := FormatFiles(paths, false)

	wantChanged := []bool{true, false, false, false}
	wantErr := []bool{false, true, false, true}
	for i, path := range paths {
		if results[i].Path != path {
			t.Errorf("result %d: expected %q, got %q", i, path, results[i].Path)
		}
		if results[i].Changed != wantChanged[i] {
			t.Errorf("%s: expected changed=%v, got %v", path, wantChanged[i], results[i].Changed)
		}
		if (errs[i] != nil) != wantErr[i] {
			t.Errorf("%s: expected error=%v, got %v", path, wantErr[i], errs[i])
		}
	}
	if got, err := os.ReadFile(paths[0]); err != nil || string(got) != "a=1\n" {
		t.Errorf("expected the check to leave messy.tf alone, got %q (%v)", got, err)
	}
}
