package cmd

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/overflow"
	"github.com/onyx-dot-app/onyx/cli/internal/sanitize"
	"github.com/spf13/cobra"
)

const defaultMaxOutputBytes = 50000

func newAskCmd(ios *iostreams.IOStreams) *cobra.Command {
	var (
		askAgentID   int
		askAgentName string
		askJSON      bool
		askQuiet     bool
		askPrompt    string
		maxOutput    int
	)

	cmd := &cobra.Command{
		Use:   "ask [question]",
		Short: "Ask a question and print the answer to stdout",
		Long: `Send a one-shot question to an Onyx agent and print the response.

The question can be provided as a positional argument, via --prompt, or piped
through stdin. When stdin contains piped data, it is sent as context along
with the question from --prompt (or used as the question itself).

When stdout is not a TTY (e.g., called by a script or AI agent), output is
automatically truncated to --max-output bytes and the full response is saved
to a temp file. Set --max-output 0 to disable truncation.`,
		Args: cobra.MaximumNArgs(1),
		Example: `  onyx-cli ask "What connectors are available?"
  onyx-cli ask --agent-id 3 "Summarize our Q4 revenue"
  onyx-cli ask --agent-name "Support Agent" "hello"
  onyx-cli ask --json "List all users" | jq '.event.content'
  cat error.log | onyx-cli ask --prompt "Find the root cause"
  echo "what is onyx?" | onyx-cli ask`,
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg, client, err := requireClient()
			if err != nil {
				return err
			}

			if askJSON && askQuiet {
				return exitcodes.New(exitcodes.BadRequest, "--json and --quiet cannot be used together")
			}

			question, err := resolveQuestion(ios, args, askPrompt)
			if err != nil {
				return err
			}

			ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
			defer stop()

			agentID, _, err := resolveAgentSelection(
				ctx,
				client,
				askAgentID,
				cmd.Flags().Changed("agent-id"),
				askAgentName,
				cmd.Flags().Changed("agent-name"),
				cfg.DefaultAgentID,
			)
			if err != nil {
				return err
			}

			parentID := -1
			ch := client.SendMessageStream(
				ctx,
				question,
				nil,
				agentID,
				&parentID,
				nil,
				nil,
			)

			// Determine truncation threshold.
			isTTY := ios.IsStdoutTTY
			truncateAt := 0 // 0 means no truncation
			if cmd.Flags().Changed("max-output") {
				truncateAt = maxOutput
			} else if !isTTY {
				truncateAt = defaultMaxOutputBytes
			}

			var sessionID string
			var lastErr error
			gotStop := false
			responseState := &models.ResponseState{}

			// Overflow writer: tees to stdout and optionally to a temp file.
			// In quiet mode, buffer everything and print once at the end.
			ow := &overflow.Writer{Limit: truncateAt, Quiet: askQuiet, Out: ios.Out, ErrOut: ios.ErrOut}

			for event := range ch {
				switch e := event.(type) {
				case models.SessionCreatedEvent:
					sessionID = e.ChatSessionID
				case models.StopEvent:
					// Keep draining: the server saves the turn after it sends stop,
					// and the rename below reads the saved history.
					gotStop = true
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
					fmt.Fprintln(ios.Out, string(data))
					if errEvt, ok := event.(models.ErrorEvent); ok {
						if errEvt.StatusCode != 0 {
							lastErr = exitcodes.Newf(exitcodes.ForHTTPStatus(errEvt.StatusCode), "%s", sanitize.Terminal(errEvt.Error))
						} else {
							lastErr = exitcodes.New(exitcodes.General, sanitize.Terminal(errEvt.Error))
						}
					}
					continue
				}

				change, err := responseState.Apply(event)
				if err != nil {
					return err
				}
				if change != nil {
					if !askQuiet {
						ow.Write(change.TextDelta())
					}
					if isTTY && !askQuiet {
						activity, err := change.Activity()
						if err != nil {
							return err
						}
						for _, line := range activity {
							fmt.Fprintf(ios.ErrOut, "\033[2m%s\033[0m\n", line)
						}
					}
				}
				switch e := event.(type) {
				case models.ErrorEvent:
					if askQuiet {
						ow.Write(responseState.Text())
					}
					ow.Finish()
					if e.StatusCode != 0 {
						return exitcodes.Newf(exitcodes.ForHTTPStatus(e.StatusCode), "%s", sanitize.Terminal(e.Error))
					}
					return exitcodes.New(exitcodes.General, sanitize.Terminal(e.Error))
				case models.StopEvent:
					if askQuiet {
						ow.Write(sanitize.Terminal(responseState.Text()))
					}
					ow.Finish()
					return nil
				}
			}

			if !askJSON {
				if askQuiet {
					ow.Write(responseState.Text())
				}
				ow.Finish()
			}

			if ctx.Err() != nil {
				if sessionID != "" {
					client.StopChatSession(context.Background(), sessionID)
				}
				return nil
			}

			if lastErr != nil {
				return lastErr
			}
			if !gotStop {
				return exitcodes.New(exitcodes.General, "stream ended unexpectedly")
			}
			nameChatSession(ctx, ios, client, sessionID)
			return nil
		},
	}

	cmd.Flags().IntVar(&askAgentID, "agent-id", 0, "Agent ID to use")
	cmd.Flags().StringVar(&askAgentName, "agent-name", "", "Agent name to use (exact or unique substring)")
	cmd.Flags().BoolVar(&askJSON, "json", false, "Output NDJSON stream events instead of plain text")
	cmd.Flags().BoolVarP(&askQuiet, "quiet", "q", false, "Buffer output and print once at end (no streaming)")
	cmd.Flags().StringVar(&askPrompt, "prompt", "", "Question text (use with piped stdin context)")
	cmd.Flags().IntVar(&maxOutput, "max-output", defaultMaxOutputBytes,
		"Max bytes to print before truncating (0 to disable, auto-enabled for non-TTY)")
	return cmd
}

// nameChatSession asks the backend to title the session. The server only titles
// on request, so without this a one-shot ask stays "New Chat" in the sidebar.
// It runs after the answer is flushed so the naming LLM call never delays output.
func nameChatSession(ctx context.Context, ios *iostreams.IOStreams, client *api.Client, sessionID string) {
	if sessionID == "" {
		return
	}
	if _, err := client.RenameChatSession(ctx, sessionID, nil); err != nil && ctx.Err() == nil {
		fmt.Fprintf(ios.ErrOut, "warning: could not name chat session: %s\n", sanitize.Terminal(err.Error()))
	}
}

// resolveQuestion builds the final question string from args, --prompt, and stdin.
func resolveQuestion(ios *iostreams.IOStreams, args []string, prompt string) (string, error) {
	hasArg := len(args) > 0
	hasPrompt := prompt != ""
	hasStdin := !ios.IsStdinTTY

	if hasArg && hasPrompt {
		return "", exitcodes.New(exitcodes.BadRequest, "specify the question as an argument or --prompt, not both")
	}

	var stdinContent string
	if hasStdin {
		const maxStdinBytes = 10 * 1024 * 1024 // 10MB
		data, err := io.ReadAll(io.LimitReader(ios.In, maxStdinBytes))
		if err != nil {
			return "", fmt.Errorf("failed to read stdin: %w", err)
		}
		stdinContent = strings.TrimSpace(string(data))
	}

	switch {
	case hasArg && stdinContent != "":
		// arg is the question, stdin is context
		return args[0] + "\n\n" + stdinContent, nil
	case hasArg:
		return args[0], nil
	case hasPrompt && stdinContent != "":
		// --prompt is the question, stdin is context
		return prompt + "\n\n" + stdinContent, nil
	case hasPrompt:
		return prompt, nil
	case stdinContent != "":
		return stdinContent, nil
	default:
		return "", exitcodes.New(exitcodes.BadRequest, "no question provided\n  Usage: onyx-cli ask \"your question\"\n  Or:    echo \"context\" | onyx-cli ask --prompt \"your question\"")
	}
}
