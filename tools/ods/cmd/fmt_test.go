package cmd

import (
	"bytes"
	"path/filepath"
	"strings"
	"testing"
)

func TestRunFmtTerraform(t *testing.T) {
	const unformatted = "a  =  1\n"
	const formatted = "a = 1\n"

	cases := []struct {
		name       string
		check      bool
		wantClean  bool
		wantStderr string
		wantFile   string
	}{
		{"check reports without rewriting", true, false, filepath.Join("infra", "main.tf") + "\n", unformatted},
		// pre-commit must see a failure so the rewritten file is restaged.
		{"write rewrites and fails", false, false, filepath.Join("infra", "main.tf") + "\n", formatted},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			root := devtoolRepo(t)
			file := filepath.Join(root, "infra", "main.tf")
			writeFile(t, file, unformatted)
			writeFile(t, filepath.Join(root, "infra", "done.tf"), formatted)

			var stderr bytes.Buffer
			clean, err := runFmtTerraform(nil, c.check, &stderr)
			if err != nil {
				t.Fatalf("runFmtTerraform: %v", err)
			}

			if clean != c.wantClean {
				t.Fatalf("expected clean=%v, got %v", c.wantClean, clean)
			}
			if got := stderr.String(); got != c.wantStderr {
				t.Fatalf("expected stderr %q, got %q", c.wantStderr, got)
			}
			if got := devtoolReadFile(t, file); got != c.wantFile {
				t.Fatalf("expected file %q, got %q", c.wantFile, got)
			}
		})
	}
}

func TestRunFmtTerraform_passesFormattedFiles(t *testing.T) {
	root := devtoolRepo(t)
	writeFile(t, filepath.Join(root, "main.tf"), "a = 1\n")

	var stderr bytes.Buffer
	clean, err := runFmtTerraform(nil, false, &stderr)
	if err != nil {
		t.Fatalf("runFmtTerraform: %v", err)
	}
	if !clean || stderr.Len() != 0 {
		t.Fatalf("expected a clean run, got clean=%v stderr=%q", clean, stderr.String())
	}
}

func TestRunFmtTerraform_leavesUnparseableFilesAlone(t *testing.T) {
	root := devtoolRepo(t)
	bad := filepath.Join(root, "bad.tf")
	writeFile(t, bad, "a = {\n")

	var stderr bytes.Buffer
	clean, err := runFmtTerraform([]string{bad}, false, &stderr)
	if err != nil {
		t.Fatalf("runFmtTerraform: %v", err)
	}

	if clean {
		t.Fatal("expected an unparseable file to fail the run")
	}
	if got := stderr.String(); !strings.HasPrefix(got, "bad.tf: ") {
		t.Fatalf("expected the parse error for bad.tf, got %q", got)
	}
	if got := devtoolReadFile(t, bad); got != "a = {\n" {
		t.Fatalf("expected the file to be left alone, got %q", got)
	}
}
