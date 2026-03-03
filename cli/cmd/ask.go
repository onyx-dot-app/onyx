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
	askAgentID int
	askJSON    bool
)

var askCmd = &cobra.Command{
	Use:   "ask [question]",
	Short: "Ask a one-shot question (non-interactive)",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		cfg := config.Load()
		if !cfg.IsConfigured() {
			return fmt.Errorf("onyx CLI is not configured — run 'onyx configure' first")
		}

		question := args[0]
		agentID := cfg.DefaultAgentID
		if cmd.Flags().Changed("agent-id") {
			agentID = askAgentID
		}

		client := api.NewClient(cfg)
		parentID := -1
		ch := client.SendMessageStream(
			context.Background(),
			question,
			nil,
			agentID,
			&parentID,
			nil,
		)

		var lastErr error
		gotStop := false
		for event := range ch {
			if askJSON {
				data, err := json.Marshal(event)
				if err != nil {
					fmt.Fprintf(os.Stderr, "Error marshaling event: %v\n", err)
					continue
				}
				fmt.Println(string(data))
				if _, ok := event.(models.ErrorEvent); ok {
					lastErr = fmt.Errorf("%s", event.(models.ErrorEvent).Error)
				}
				if _, ok := event.(models.StopEvent); ok {
					gotStop = true
				}
				continue
			}

			switch e := event.(type) {
			case models.MessageDeltaEvent:
				fmt.Print(e.Content)
			case models.ErrorEvent:
				return fmt.Errorf("%s", e.Error)
			case models.StopEvent:
				fmt.Println()
				return nil
			}
		}

		if lastErr != nil {
			return lastErr
		}
		if !gotStop {
			if !askJSON {
				fmt.Println()
			}
			return fmt.Errorf("stream ended unexpectedly")
		}
		if !askJSON {
			fmt.Println()
		}
		return nil
	},
}

func init() {
	askCmd.Flags().IntVar(&askAgentID, "agent-id", 0, "Agent ID to use")
	askCmd.Flags().BoolVar(&askJSON, "json", false, "Output raw JSON events")
	rootCmd.AddCommand(askCmd)
}
