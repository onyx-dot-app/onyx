package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/sergi/go-diff/diffmatchpatch"
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/composegen"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/deployfilessync"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// NewGenerateComposeCommand creates the generate-compose command.
func NewGenerateComposeCommand() *cobra.Command {
	var write bool

	cmd := &cobra.Command{
		Use:   "generate-compose",
		Short: "Generate the docker compose files from the shared template",
		Long: `Generate the standalone docker compose files from docker-compose.template.yml.

docker-compose.yml, docker-compose.prod.yml and
docker-compose.prod-no-letsencrypt.yml are generated files. Edit
docker-compose.template.yml instead, then regenerate with:

  ods generate-compose --write

The command also syncs the deployment files that onyx-cli embeds via
go:embed (the generated docker-compose.yml and docker-compose.prod.yml, the
lite/craft overlays, the env templates, the nginx config, and the
install-root README) into
byte-identical copies under cli/internal/deploy/deployfiles/embedded/ —
go:embed cannot reference files outside the cli module, and the copies must
always be refreshed together with the generated compose files.

Without --write the command runs in check mode: it prints a diff and exits
non-zero if any generated file or embedded copy is out of date. The
docker-compose-sync pre-commit hook runs --write automatically for commits
touching any of the source or output files.

Template directives are line comments starting with the sentinel "#!". They
are always stripped from the output. <variants> is a comma-separated subset
of: default, prod, no-letsencrypt (mapping to the three generated files).

  #!for <variants>            include the enclosed lines only for <variants>;
  ...                         must be closed with #!endfor, no nesting
  #!endfor

  #!only <variants>           shorthand: applies to exactly the next line

  #!value <variants>: <text>  per-variant text for the line that follows: the
                              directive's own indentation plus <text> replaces
                              the next line for the listed variants; unlisted
                              variants keep the line as written. Stack several
                              #!value directives for three-way splits.

  #!# <text>                  template-only comment, never emitted`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			runGenerateCompose(write)
		},
	}

	cmd.Flags().BoolVar(&write, "write", false, "Rewrite the generated files instead of checking them")

	return cmd
}

func runGenerateCompose(write bool) {
	dir := composeDir()

	data, err := os.ReadFile(filepath.Join(dir, composegen.TemplateName))
	if err != nil {
		log.Fatalf("Failed to read template: %v", err)
	}
	templateLines := strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")

	rendered, err := composegen.GenerateAll(templateLines)
	if err != nil {
		log.Fatalf("%v", err)
	}

	var stale []string
	for _, variant := range composegen.Variants {
		filename := variant.Filename
		content := rendered[filename]
		path := filepath.Join(dir, filename)

		current, err := os.ReadFile(path)
		if err != nil && !os.IsNotExist(err) {
			log.Fatalf("Failed to read %s: %v", filename, err)
		}
		if string(current) == content {
			continue
		}

		if write {
			if err := os.WriteFile(path, []byte(content), 0644); err != nil {
				log.Fatalf("Failed to write %s: %v", filename, err)
			}
			fmt.Printf("regenerated %s\n", filename)
		} else {
			fmt.Fprint(os.Stderr, lineDiff(filename, composegen.TemplateName, string(current), content))
			stale = append(stale, filename)
		}
	}

	// Sync the embedded copies for onyx-cli after the variants, so the copy
	// of docker-compose.yml reflects the freshly rendered output.
	repoRoot, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}
	var results []deployfilessync.Result
	if write {
		results, err = deployfilessync.Write(repoRoot)
	} else {
		results, err = deployfilessync.Check(repoRoot)
	}
	if err != nil {
		log.Fatalf("%v", err)
	}
	for _, r := range results {
		if !r.Stale {
			continue
		}
		if write {
			fmt.Printf("synced embedded copy of %s\n", r.RelPath)
		} else {
			fmt.Fprint(os.Stderr, lineDiff("embedded/"+r.RelPath, "deployment/"+r.RelPath, r.Dest, r.Source))
			stale = append(stale, "embedded copy of "+r.RelPath)
		}
	}

	if len(stale) > 0 {
		for _, filename := range stale {
			fmt.Fprintf(os.Stderr, "%s is stale (re-run with --write).\n", filename)
		}
		os.Exit(1)
	}
}

// lineDiff returns a compact line-based diff (changed lines only) between the
// on-disk file and the freshly rendered content.
func lineDiff(filename, source, current, generated string) string {
	dmp := diffmatchpatch.New()
	a, b, lineArray := dmp.DiffLinesToChars(current, generated)
	diffs := dmp.DiffCharsToLines(dmp.DiffMain(a, b, false), lineArray)

	var sb strings.Builder
	fmt.Fprintf(&sb, "--- %s\n+++ %s (from %s)\n", filename, filename, source)
	for _, d := range diffs {
		var prefix string
		switch d.Type {
		case diffmatchpatch.DiffDelete:
			prefix = "-"
		case diffmatchpatch.DiffInsert:
			prefix = "+"
		default:
			continue
		}
		for _, line := range strings.Split(strings.TrimSuffix(d.Text, "\n"), "\n") {
			sb.WriteString(prefix + line + "\n")
		}
	}
	return sb.String()
}
