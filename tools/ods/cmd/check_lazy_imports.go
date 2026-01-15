package cmd

import (
	"fmt"
	"os"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/lazyimports"
)

// NewCheckLazyImportsCommand creates the check-lazy-imports command.
func NewCheckLazyImportsCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "check-lazy-imports [paths...]",
		Short: "Check that specified modules are only lazily imported",
		Long: `Check that specified modules are only lazily imported in Python files.

Certain modules (like openai, tiktoken, transformers, etc.) should only be
imported inside functions, not at the module level. This command scans Python
files to detect violations of this rule.

Optionally provide files or directories to limit the check; if none are
provided, all backend Python files are scanned.

Examples:
  ods check-lazy-imports                     # Check all backend Python files
  ods check-lazy-imports onyx/llm/           # Check only files in onyx/llm/
  ods check-lazy-imports onyx/chat/chat.py   # Check a specific file`,
		Run: func(cmd *cobra.Command, args []string) {
			runCheckLazyImports(args)
		},
	}

	return cmd
}

func runCheckLazyImports(providedPaths []string) {
	modules := lazyimports.DefaultLazyImportModules()

	violations, allViolatedModules, err := lazyimports.CheckLazyImports(modules, providedPaths)
	if err != nil {
		log.Fatalf("Error checking lazy imports: %v", err)
	}

	if len(violations) > 0 {
		for _, v := range violations {
			log.Errorf("\n❌ Eager import violations found in %s:", v.RelPath)

			for _, line := range v.ViolationLines {
				log.Errorf("  Line %d: %s", line.LineNum, line.Content)
			}

			if len(v.ViolatedModules) > 0 {
				log.Errorf("  💡 You must lazy import %s within functions when needed",
					lazyimports.FormatViolatedModules(v.ViolatedModules))
			}
		}

		violatedModulesStr := lazyimports.FormatViolatedModules(allViolatedModules)
		fmt.Fprintf(os.Stderr, "\nFound eager imports of %s. You must import them only when needed.\n", violatedModulesStr)
		os.Exit(1)
	}

	log.Info("✅ All lazy modules are properly imported!")
}

