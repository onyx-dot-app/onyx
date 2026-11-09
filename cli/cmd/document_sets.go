package cmd

import (
	"encoding/json"
	"fmt"
	"text/tabwriter"

	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/sanitize"
	"github.com/spf13/cobra"
)

func newDocumentSetsCmd(ios *iostreams.IOStreams) *cobra.Command {
	var documentSetsJSON bool

	cmd := &cobra.Command{
		Use:   "document-sets",
		Short: "List document sets you can search (ID, name, description)",
		Long: `List the document sets the current user can search.

Pass the names to "onyx-cli search --document-set" to limit a search to those
document sets. By default, output is a human-readable table. Use --json for
machine-readable output.`,
		Example: `  onyx-cli document-sets
  onyx-cli document-sets --json | jq -r '.[].name'`,
		RunE: func(cmd *cobra.Command, args []string) error {
			_, client, err := requireClient()
			if err != nil {
				return err
			}

			documentSets, err := client.ListDocumentSets(cmd.Context())
			if err != nil {
				return apiErrorToExit(err, "failed to list document sets")
			}

			if documentSetsJSON {
				if documentSets == nil {
					documentSets = []models.DocumentSetSummary{}
				}
				data, err := json.MarshalIndent(documentSets, "", "  ")
				if err != nil {
					return fmt.Errorf("failed to marshal document sets: %w", err)
				}
				fmt.Fprintln(ios.Out, string(data))
				return nil
			}

			if len(documentSets) == 0 {
				fmt.Fprintln(ios.Out, "No document sets available.")
				return nil
			}

			w := tabwriter.NewWriter(ios.Out, 0, 4, 2, ' ', 0)
			fmt.Fprintln(w, "ID\tNAME\tDESCRIPTION")
			for _, ds := range documentSets {
				desc := ""
				if ds.Description != nil {
					desc = *ds.Description
				}
				if r := []rune(desc); len(r) > 60 {
					desc = string(r[:57]) + "..."
				}
				fmt.Fprintf(w, "%d\t%s\t%s\n", ds.ID, sanitize.Line(ds.Name), sanitize.Line(desc))
			}
			_ = w.Flush()

			return nil
		},
	}

	cmd.Flags().BoolVar(&documentSetsJSON, "json", false, "Output document sets as JSON")

	return cmd
}
