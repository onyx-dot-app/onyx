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
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/spf13/cobra"
	"golang.org/x/term"
)

const defaultMaxOutputBytes = 4096

func newAskCmd() *cobra.Command {
	var (
		askAgentID int
		askJSON    bool
		askQuiet   bool
		askPrompt  string
		maxOutput  int
	)

	cmd := &cobra.Command{
		Use:   "ask [question]",
		Short: "Ask a one-shot question (non-interactive)",
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
  onyx-cli ask --json "List all users" | jq '.event.content'
  cat error.log | onyx-cli ask --prompt "Find the root cause"
  echo "what is onyx?" | onyx-cli ask`,
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := config.Load()
			if !cfg.IsConfigured() {
				return exitcodes.New(exitcodes.NotConfigured, "onyx CLI is not configured\n  Run: onyx-cli configure")
			}

			question, err := resolveQuestion(args, askPrompt)
			if err != nil {
				return err
			}

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

			// Determine truncation threshold.
			truncateAt := 0 // 0 means no truncation
			if cmd.Flags().Changed("max-output") {
				truncateAt = maxOutput
			} else if !term.IsTerminal(int(os.Stdout.Fd())) {
				truncateAt = defaultMaxOutputBytes
			}

			var sessionID string
			var lastErr error
			gotStop := false

			// Overflow writer: tees to stdout and optionally to a temp file.
			// In quiet mode, buffer everything and print once at the end.
			ow := &overflowWriter{limit: truncateAt, quiet: askQuiet}

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
					if !askQuiet {
						fmt.Println(string(data))
					}
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
					ow.Write(e.Content)
				case models.ErrorEvent:
					ow.Finish()
					return fmt.Errorf("%s", e.Error)
				case models.StopEvent:
					ow.Finish()
					return nil
				}
			}

			ow.Finish()

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
				return fmt.Errorf("stream ended unexpectedly")
			}
			return nil
		},
	}

	cmd.Flags().IntVar(&askAgentID, "agent-id", 0, "Agent ID to use")
	cmd.Flags().BoolVar(&askJSON, "json", false, "Output raw JSON events")
	cmd.Flags().BoolVarP(&askQuiet, "quiet", "q", false, "Buffer output and print once at end (no streaming)")
	cmd.Flags().StringVar(&askPrompt, "prompt", "", "Question text (use with piped stdin context)")
	cmd.Flags().IntVar(&maxOutput, "max-output", defaultMaxOutputBytes,
		"Max bytes to print before truncating (0 to disable, auto-enabled for non-TTY)")
	return cmd
}

// resolveQuestion builds the final question string from args, --prompt, and stdin.
func resolveQuestion(args []string, prompt string) (string, error) {
	hasArg := len(args) > 0
	hasPrompt := prompt != ""
	hasStdin := !term.IsTerminal(int(os.Stdin.Fd()))

	var stdinContent string
	if hasStdin {
		const maxStdinBytes = 10 * 1024 * 1024 // 10MB
		data, err := io.ReadAll(io.LimitReader(os.Stdin, maxStdinBytes))
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

// overflowWriter handles streaming output with optional truncation.
// When limit > 0, it tees all content to a temp file and stops writing
// to stdout after limit bytes. When limit == 0, it writes directly to stdout.
type overflowWriter struct {
	limit      int
	quiet      bool
	written    int
	totalBytes int
	truncated  bool
	buf        strings.Builder // accumulates content for temp file or quiet mode
}

func (w *overflowWriter) Write(s string) {
	w.totalBytes += len(s)

	// Quiet mode: buffer everything, print nothing
	if w.quiet {
		w.buf.WriteString(s)
		return
	}

	if w.limit <= 0 {
		fmt.Print(s)
		return
	}

	// Always accumulate for the temp file
	w.buf.WriteString(s)

	if w.truncated {
		return
	}

	remaining := w.limit - w.written
	if len(s) <= remaining {
		fmt.Print(s)
		w.written += len(s)
	} else {
		// Print up to the limit, then stop
		if remaining > 0 {
			fmt.Print(s[:remaining])
			w.written += remaining
		}
		w.truncated = true
	}
}

func (w *overflowWriter) Finish() {
	// Quiet mode: print buffered content at once
	if w.quiet {
		fmt.Println(w.buf.String())
		return
	}

	if !w.truncated {
		fmt.Println()
		return
	}

	// Write full content to temp file
	tmpFile, err := os.CreateTemp("", "onyx-ask-*.txt")
	if err != nil {
		fmt.Fprintf(os.Stderr, "\nwarning: could not create temp file: %v\n", err)
		fmt.Println()
		return
	}

	_, writeErr := tmpFile.WriteString(w.buf.String())
	_ = tmpFile.Close()
	if writeErr != nil {
		fmt.Fprintf(os.Stderr, "\nwarning: could not write temp file: %v\n", writeErr)
		fmt.Println()
		return
	}

	fmt.Printf("\n\n--- response truncated (%d bytes total) ---\n", w.totalBytes)
	fmt.Printf("Full response: %s\n", tmpFile.Name())
	fmt.Printf("Explore:\n")
	fmt.Printf("  cat %s | grep \"<pattern>\"\n", tmpFile.Name())
	fmt.Printf("  cat %s | tail -50\n", tmpFile.Name())
}
