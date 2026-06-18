package cmd

import (
	"encoding/json"
	"fmt"
	"text/tabwriter"

	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/spf13/cobra"
)

func newAgentsCmd(ios *iostreams.IOStreams) *cobra.Command {
	var agentsJSON bool

	cmd := &cobra.Command{
		Use:   "agents",
		Short: "List available agents (ID, name, description)",
		Long: `List all visible agents configured on the Onyx server.

By default, output is a human-readable table with ID, name, and description.
Use --json for machine-readable output.`,
		Example: `  onyx-cli agents
  onyx-cli agents --json
  onyx-cli agents --json | jq '.[].name'`,
		RunE: func(cmd *cobra.Command, args []string) error {
			_, client, err := requireClient()
			if err != nil {
				return err
			}

			agents, err := client.ListAgents(cmd.Context())
			if err != nil {
				return apiErrorToExit(err, "failed to list agents")
			}

			if agentsJSON {
				data, err := json.MarshalIndent(agents, "", "  ")
				if err != nil {
					return fmt.Errorf("failed to marshal agents: %w", err)
				}
				fmt.Fprintln(ios.Out, string(data))
				return nil
			}

			if len(agents) == 0 {
				fmt.Fprintln(ios.Out, "No agents available.")
				return nil
			}

			w := tabwriter.NewWriter(ios.Out, 0, 4, 2, ' ', 0)
			fmt.Fprintln(w, "ID\tNAME\tDESCRIPTION")
			for _, a := range agents {
				desc := a.Description
				if len(desc) > 60 {
					desc = desc[:57] + "..."
				}
				fmt.Fprintf(w, "%d\t%s\t%s\n", a.ID, a.Name, desc)
			}
			_ = w.Flush()

			return nil
		},
	}

	cmd.Flags().BoolVar(&agentsJSON, "json", false, "Output agents as JSON")

	return cmd
}
