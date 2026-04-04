package cmd

import (
	"encoding/json"
	"fmt"
	"text/tabwriter"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/spf13/cobra"
)

func newAgentsCmd() *cobra.Command {
	var agentsJSON bool

	cmd := &cobra.Command{
		Use:   "agents",
		Short: "List available agents",
		Long: `List all visible agents configured on the Onyx server.

By default, output is a human-readable table with ID, name, and description.
Use --json for machine-readable output.`,
		Example: `  onyx-cli agents
  onyx-cli agents --json
  onyx-cli agents --json | jq '.[].name'`,
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := config.Load()
			if !cfg.IsConfigured() {
				return exitcodes.New(exitcodes.NotConfigured, "onyx CLI is not configured\n  Run: onyx-cli configure")
			}

			client := api.NewClient(cfg)
			agents, err := client.ListAgents(cmd.Context())
			if err != nil {
				return fmt.Errorf("failed to list agents: %w\n  Check your connection with: onyx-cli validate-config", err)
			}

			if agentsJSON {
				data, err := json.MarshalIndent(agents, "", "  ")
				if err != nil {
					return fmt.Errorf("failed to marshal agents: %w", err)
				}
				fmt.Println(string(data))
				return nil
			}

			if len(agents) == 0 {
				fmt.Println("No agents available.")
				return nil
			}

			w := tabwriter.NewWriter(cmd.OutOrStdout(), 0, 4, 2, ' ', 0)
			_, _ = fmt.Fprintln(w, "ID\tNAME\tDESCRIPTION")
			for _, a := range agents {
				desc := a.Description
				if len(desc) > 60 {
					desc = desc[:57] + "..."
				}
				_, _ = fmt.Fprintf(w, "%d\t%s\t%s\n", a.ID, a.Name, desc)
			}
			_ = w.Flush()

			return nil
		},
	}

	cmd.Flags().BoolVar(&agentsJSON, "json", false, "Output agents as JSON")

	return cmd
}
