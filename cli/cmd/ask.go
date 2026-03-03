package cmd

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/spf13/cobra"
)

var (
	askPersonaID int
	askJSON      bool
)

var askCmd = &cobra.Command{
	Use:   "ask [question]",
	Short: "Ask a one-shot question (non-interactive)",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		cfg := config.Load()
		if !cfg.IsConfigured() {
			fmt.Fprintln(os.Stderr, "Error: Onyx CLI is not configured. Run 'onyx-cli configure' first.")
			os.Exit(1)
		}

		question := args[0]
		personaID := cfg.DefaultPersonaID
		if cmd.Flags().Changed("persona-id") {
			personaID = askPersonaID
		}

		client := api.NewClient(cfg)
		parentID := -1
		ch := client.SendMessageStream(
			context.Background(),
			question,
			nil,
			personaID,
			&parentID,
			nil,
		)

		for event := range ch {
			if askJSON {
				data, _ := json.Marshal(event)
				fmt.Println(string(data))
				continue
			}

			switch e := event.(type) {
			case models.MessageDeltaEvent:
				fmt.Print(e.Content)
			case models.ErrorEvent:
				fmt.Fprintf(os.Stderr, "\nError: %s\n", e.Error)
				os.Exit(1)
			case models.StopEvent:
				fmt.Println()
				return nil
			}
		}

		if !askJSON {
			fmt.Println()
		}
		return nil
	},
}

func init() {
	askCmd.Flags().IntVar(&askPersonaID, "persona-id", 0, "Persona/assistant ID to use")
	askCmd.Flags().BoolVar(&askJSON, "json", false, "Output raw JSON events")
	rootCmd.AddCommand(askCmd)
}
