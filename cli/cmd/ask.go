package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/spf13/cobra"
)

func newAskCmd() *cobra.Command {
	var (
		askAgentID int
		askJSON    bool
	)

	cmd := &cobra.Command{
		Use:   "ask [question]",
		Short: "Ask a one-shot question (non-interactive)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := config.Load()
			if !cfg.IsConfigured() {
				return fmt.Errorf("onyx CLI is not configured — run 'onyx-cli configure' first")
			}

			question := args[0]
			agentID := cfg.DefaultAgentID
			if cmd.Flags().Changed("agent-id") {
				agentID = askAgentID
			}

			ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
			defer stop()

			client := api.NewClient(cfg)
			parentID := -1
			ch := client.SendMessageStream(
				ctx,
				question,
				nil,
				agentID,
				&parentID,
				nil,
			)

			var sessionID string
			var lastErr error
			gotStop := false
			for event := range ch {
				if e, ok := event.(models.SessionCreatedEvent); ok {
					sessionID = e.ChatSessionID
				}

				if askJSON {
					wrapped := struct {
						Type  string             `json:"type"`
						Event models.StreamEvent `json:"event"`
					}{
						Type:  event.EventType(),
						Event: event,
					}
					data, err := json.Marshal(wrapped)
					if err != nil {
						return fmt.Errorf("error marshaling event: %w", err)
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

			if ctx.Err() != nil {
				if sessionID != "" {
					client.StopChatSession(sessionID)
				}
				if !askJSON {
					fmt.Println()
				}
				return nil
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

	cmd.Flags().IntVar(&askAgentID, "agent-id", 0, "Agent ID to use")
	cmd.Flags().BoolVar(&askJSON, "json", false, "Output raw JSON events")
	// Suppress cobra's default error/usage on RunE errors
	return cmd
}
