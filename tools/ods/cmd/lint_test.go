package cmd

import (
	"bytes"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/terraform"
)

const devtoolLintHint = "Move the value to the caller, or append '# public-safe: ok' if the line is genuinely safe to publish.\n"

func TestRunLintTerraform_reportsFindingsInPublishedModules(t *testing.T) {
	root := devtoolRepo(t)
	writeFile(t, filepath.Join(root, "deployment", "terraform", "modules", "a", "main.tf"),
		"variable \"account\" {\n  default = \"123456789012\"\n}\n")
	writeFile(t, filepath.Join(root, "deployment", "terraform", "modules", "b", "main.tf"),
		"variable \"region\" {\n  default = \"us-east-2\"\n}\n")
	// Only deployment/terraform is published, so this file is not scanned.
	writeFile(t, filepath.Join(root, "internal", "main.tf"), "a = \"210987654321\"\n")

	var stderr bytes.Buffer
	clean, err := runLintTerraform(nil, &stderr)
	if err != nil {
		t.Fatalf("runLintTerraform: %v", err)
	}

	if clean {
		t.Fatal("expected findings")
	}
	finding := terraform.Finding{
		Path:  filepath.Join("deployment", "terraform", "modules", "a", "main.tf"),
		Line:  2,
		Rule:  terraform.RuleAccountID,
		Value: "123456789012",
	}
	want := "Internal values found in published Terraform modules:\n\n  " + finding.String() + "\n\n" + devtoolLintHint
	if got := stderr.String(); got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestRunLintTerraform_passesCleanModules(t *testing.T) {
	root := devtoolRepo(t)
	writeFile(t, filepath.Join(root, "deployment", "terraform", "main.tf"),
		"a = \"123456789012\" # public-safe: ok\n")

	var stderr bytes.Buffer
	clean, err := runLintTerraform(nil, &stderr)
	if err != nil {
		t.Fatalf("runLintTerraform: %v", err)
	}
	if !clean || stderr.Len() != 0 {
		t.Fatalf("expected a clean run, got clean=%v stderr=%q", clean, stderr.String())
	}
}

func TestRunLintTerraform_checksExplicitFilesOutsideARepository(t *testing.T) {
	dir := t.TempDir()
	t.Chdir(dir)
	file := filepath.Join(dir, "main.tf")
	writeFile(t, file, "a = \"123456789012\"\n")

	var stderr bytes.Buffer
	clean, err := runLintTerraform([]string{file}, &stderr)
	if err != nil {
		t.Fatalf("runLintTerraform: %v", err)
	}
	// With no repository root the path is shown as given.
	if clean || !strings.Contains(stderr.String(), "  "+file+":1: ") {
		t.Fatalf("expected a finding for %s, got clean=%v stderr=%q", file, clean, stderr.String())
	}
}

func TestRunTerraformCommands_errors(t *testing.T) {
	runners := []struct {
		name string
		run  func(args []string) (bool, error)
	}{
		{"lint", func(args []string) (bool, error) { return runLintTerraform(args, &bytes.Buffer{}) }},
		{"fmt", func(args []string) (bool, error) { return runFmtTerraform(args, false, &bytes.Buffer{}) }},
	}
	for _, r := range runners {
		t.Run(r.name+" without a repository or paths", func(t *testing.T) {
			gitrelChdirOutsideRepo(t)
			if _, err := r.run(nil); err == nil || !strings.HasPrefix(err.Error(), "Cannot locate the repository root") {
				t.Fatalf("expected a repository root error, got %v", err)
			}
		})
		t.Run(r.name+" with a missing path", func(t *testing.T) {
			devtoolRepo(t)
			if _, err := r.run([]string{"missing.tf"}); err == nil || !strings.HasPrefix(err.Error(), "Cannot collect Terraform files") {
				t.Fatalf("expected a discovery error, got %v", err)
			}
		})
	}
}
