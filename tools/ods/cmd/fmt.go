package cmd

import (
	"fmt"
	"io"
	"os"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/terraform"
)

// NewFmtCommand creates the fmt command group.
func NewFmtCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:     "fmt",
		Aliases: []string{"format"},
		Short:   "Format repository sources",
	}
	cmd.AddCommand(newFmtTerraformCommand())
	return cmd
}

func newFmtTerraformCommand() *cobra.Command {
	var check bool

	cmd := &cobra.Command{
		Use:     "tf [paths...]",
		Aliases: []string{"terraform"},
		Short:   "Format Terraform files to the canonical style",
		Long: `Rewrite Terraform files into the canonical HCL style.

This applies the same formatter as 'terraform fmt', so the output matches
terraform byte for byte, but it needs no terraform binary. A file that does
not parse is reported and left alone.

Files and directories may be given to limit the run. With no arguments, the
whole repository is scanned.

Examples:
  ods fmt tf                       # Format every .tf file in the repository
  ods fmt tf deployment/terraform  # Format one subtree
  ods fmt tf --check               # Report unformatted files, change nothing`,
		Run: func(cmd *cobra.Command, args []string) {
			clean, err := runFmtTerraform(args, check, os.Stderr)
			if err != nil {
				log.Fatal(err)
			}
			if !clean {
				os.Exit(1)
			}
		},
	}

	cmd.Flags().BoolVar(&check, "check", false, "Report unformatted files without rewriting them")

	return cmd
}

// runFmtTerraform writes unparseable and changed files to stderr and reports
// whether every file was already formatted.
func runFmtTerraform(args []string, check bool, stderr io.Writer) (bool, error) {
	// The repository root only shortens paths and supplies the default target,
	// so explicit arguments still work outside a checkout.
	root, err := paths.GitRoot()
	if err != nil && len(args) == 0 {
		return false, fatalErrorf("Cannot locate the repository root: %v", err)
	}

	roots := args
	if len(roots) == 0 {
		roots = []string{root}
	}

	files, err := terraform.Discover(roots)
	if err != nil {
		return false, fatalErrorf("Cannot collect Terraform files: %v", err)
	}

	results, errs := terraform.FormatFiles(files, !check)

	var changed []string
	var failed bool
	for i, file := range files {
		if err := errs[i]; err != nil {
			_, _ = fmt.Fprintf(stderr, "%s: %v\n", relativeTo(root, file), err)
			failed = true
			continue
		}
		if results[i].Changed {
			changed = append(changed, relativeTo(root, file))
		}
	}

	for _, path := range changed {
		_, _ = fmt.Fprintln(stderr, path)
	}

	// pre-commit treats a rewritten file as a failure so the commit restages it.
	if failed || len(changed) > 0 {
		return false, nil
	}
	log.Info("✅ All Terraform files are formatted!")
	return true, nil
}
