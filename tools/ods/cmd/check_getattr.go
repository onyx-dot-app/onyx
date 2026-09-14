package cmd

import (
	"fmt"
	"os"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/pycheck"
)

// NewCheckGetattrCommand creates the check-getattr command.
func NewCheckGetattrCommand() *cobra.Command {
	var annotate bool
	cmd := &cobra.Command{
		Use:   "check-getattr [paths...]",
		Short: "Check that backend Python code does not reference the getattr builtin",
		Long: `Check that backend Python code does not reference the getattr builtin.

getattr hides attribute access from the type checker. Use plain attribute
access when the attribute name is statically known. When it is genuinely
dynamic, suppress the finding with an 'ods: ignore[getattr]' comment on the
same line, plus a brief justification:

  value = getattr(obj, field_name)  # ods: ignore[getattr] Dynamic field lookup.

String literal contents and comments never match; replacement fields inside
f-strings are scanned as code. Optionally provide files or directories to
limit the check; if none are provided, all backend Python files are scanned.

Examples:
  ods check-getattr                   # Check all backend Python files
  ods check-getattr onyx/chat/        # Check only files in onyx/chat/
  ods check-getattr --annotate        # Append ignore markers to violating lines`,
		Run: func(cmd *cobra.Command, args []string) {
			runCheckGetattr(args, annotate)
		},
	}
	cmd.Flags().BoolVar(&annotate, "annotate", false, "append ignore markers to violating lines (baseline maintenance)")
	return cmd
}

func runCheckGetattr(providedPaths []string, annotate bool) {
	rule := pycheck.NewBannedName("getattr")

	if annotate {
		runAnnotateGetattr(rule, providedPaths)
		return
	}

	violations, err := pycheck.Check(rule, providedPaths)
	if err != nil {
		log.Fatalf("Error checking getattr references: %v", err)
	}

	if len(violations) > 0 {
		total := 0
		for _, v := range violations {
			log.Errorf("\n❌ getattr references found in %s:", v.RelPath)
			for _, line := range v.ViolationLines {
				log.Errorf("  Line %d: %s", line.LineNum, line.Content)
			}
			total += len(v.ViolationLines)
		}
		log.Errorf("\n💡 getattr hides attribute access from the type checker. Use plain attribute access when the name is statically known; if it is genuinely dynamic, add '# ods: ignore[getattr]' with a brief justification.")
		fmt.Fprintf(os.Stderr, "\nFound %d getattr reference(s) in %d file(s).\n", total, len(violations))
		os.Exit(1)
	}

	log.Info("✅ No getattr references found!")
}

func runAnnotateGetattr(rule pycheck.BannedName, providedPaths []string) {
	result, err := pycheck.Annotate(rule, providedPaths)
	if err != nil {
		log.Fatalf("Error annotating getattr references: %v", err)
	}

	log.Infof("Annotated %d line(s) in %d file(s)", result.AnnotatedLines, result.AnnotatedFiles)

	if len(result.ManualFiles) > 0 {
		for _, v := range result.ManualFiles {
			log.Errorf("\n❌ Cannot annotate mechanically in %s:", v.RelPath)
			for _, line := range v.ViolationLines {
				log.Errorf("  Line %d: %s", line.LineNum, line.Content)
			}
		}
		fmt.Fprintf(os.Stderr, "\nSome lines need a manual 'ods: ignore[getattr]' marker.\n")
		os.Exit(1)
	}
}
