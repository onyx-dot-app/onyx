package cmd

import (
	"encoding/json"
	"fmt"
	"text/tabwriter"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/spf13/cobra"
)

var agentsJSON bool

var agentsCmd = &cobra.Command{
	Use:   "agents",
	Short: "List available agents",
	RunE: func(cmd *cobra.Command, args []string) error {
		cfg := config.Load()
		if !cfg.IsConfigured() {
			return fmt.Errorf("onyx CLI is not configured — run 'onyx configure' first")
		}

		client := api.NewClient(cfg)
		agents, err := client.ListAgents()
		if err != nil {
			return fmt.Errorf("failed to list agents: %w", err)
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
		fmt.Fprintln(w, "ID\tNAME\tDESCRIPTION")
		for _, a := range agents {
			desc := a.Description
			if len(desc) > 60 {
				desc = desc[:57] + "..."
			}
			fmt.Fprintf(w, "%d\t%s\t%s\n", a.ID, a.Name, desc)
		}
		w.Flush()

		return nil
	},
}

func init() {
	agentsCmd.Flags().BoolVar(&agentsJSON, "json", false, "Output agents as JSON")
	rootCmd.AddCommand(agentsCmd)
}
