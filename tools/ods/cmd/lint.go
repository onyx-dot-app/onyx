package cmd

import (
	"fmt"
	"io"
	"os"
	"path/filepath"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/terraform"
)

// NewLintCommand creates the lint command group.
func NewLintCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "lint",
		Short: "Run repository linters",
	}
	cmd.AddCommand(newLintTerraformCommand())
	return cmd
}

func newLintTerraformCommand() *cobra.Command {
	return &cobra.Command{
		Use:     "tf [paths...]",
		Aliases: []string{"terraform"},
		Short:   "Fail on internal values in published Terraform modules",
		Long: `Check published Terraform modules for values that must stay internal.

The modules under deployment/terraform are published, but they stay in sync
with the infrastructure Onyx runs. That makes it easy to carry an internal
value across by accident -- an office IP in a variable default is the case
this check was written for.

The check looks for objective patterns only: AWS account ids, access key ids,
routable IPv4 CIDRs, and email addresses. It cannot screen for customer names,
because listing them here would leak them; that stays a review step.

Add a trailing '# public-safe: ok' comment to accept a specific line.

Files and directories may be given to limit the check. With no arguments,
deployment/terraform is scanned.

Examples:
  ods lint tf                                    # Check all published modules
  ods lint tf deployment/terraform/modules/aws   # Check one subtree
  ods lint tf path/to/main.tf                    # Check a single file`,
		Run: func(cmd *cobra.Command, args []string) {
			clean, err := runLintTerraform(args, os.Stderr)
			if err != nil {
				log.Fatal(err)
			}
			if !clean {
				os.Exit(1)
			}
		},
	}
}

// runLintTerraform writes any findings to stderr and reports whether there
// were none.
func runLintTerraform(args []string, stderr io.Writer) (bool, error) {
	// The repository root only shortens paths and supplies the default target,
	// so explicit arguments still work outside a checkout.
	root, err := paths.GitRoot()
	if err != nil && len(args) == 0 {
		return false, fatalErrorf("Cannot locate the repository root: %v", err)
	}

	roots := args
	if len(roots) == 0 {
		roots = []string{filepath.Join(root, "deployment", "terraform")}
	}

	files, err := terraform.Discover(roots)
	if err != nil {
		return false, fatalErrorf("Cannot collect Terraform files: %v", err)
	}

	var findings []terraform.Finding
	for _, file := range files {
		found, err := terraform.LintFile(file, relativeTo(root, file))
		if err != nil {
			return false, fatalErrorf("Cannot read %s: %v", file, err)
		}
		findings = append(findings, found...)
	}

	if len(findings) == 0 {
		log.Info("✅ No internal values found in published Terraform modules!")
		return true, nil
	}

	_, _ = fmt.Fprintln(stderr, "Internal values found in published Terraform modules:")
	_, _ = fmt.Fprintln(stderr)
	for _, finding := range findings {
		_, _ = fmt.Fprintf(stderr, "  %s\n", finding)
	}
	_, _ = fmt.Fprintln(stderr)
	_, _ = fmt.Fprintln(stderr, "Move the value to the caller, or append '# public-safe: ok' if the line is genuinely safe to publish.")
	return false, nil
}

// relativeTo shortens a path for display, and falls back to the path itself
// when it sits outside the repository.
func relativeTo(root, path string) string {
	abs, err := filepath.Abs(path)
	if err != nil {
		return path
	}
	rel, err := filepath.Rel(root, abs)
	if err != nil {
		return path
	}
	return rel
}
