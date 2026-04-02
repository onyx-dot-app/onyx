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

			if askJSON && askQuiet {
				return exitcodes.New(exitcodes.BadRequest, "--json and --quiet cannot be used together")
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

	if hasArg && hasPrompt {
		return "", exitcodes.New(exitcodes.BadRequest, "specify the question as an argument or --prompt, not both")
	}

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
// When limit > 0, it streams to a temp file on disk (not memory) and stops
// writing to stdout after limit bytes. When limit == 0, it writes directly
// to stdout. In quiet mode, it buffers in memory and prints once at the end.
type overflowWriter struct {
	limit      int
	quiet      bool
	written    int
	totalBytes int
	truncated  bool
	buf        strings.Builder // used only in quiet mode
	tmpFile    *os.File        // used only in truncation mode (limit > 0)
}

func (w *overflowWriter) Write(s string) {
	w.totalBytes += len(s)

	// Quiet mode: buffer in memory, print nothing
	if w.quiet {
		w.buf.WriteString(s)
		return
	}

	if w.limit <= 0 {
		fmt.Print(s)
		return
	}

	// Truncation mode: stream all content to temp file on disk
	if w.tmpFile == nil {
		f, err := os.CreateTemp("", "onyx-ask-*.txt")
		if err != nil {
			// Fall back to no-truncation if we can't create the file
			fmt.Fprintf(os.Stderr, "warning: could not create temp file: %v\n", err)
			w.limit = 0
			fmt.Print(s)
			return
		}
		w.tmpFile = f
	}
	_, _ = w.tmpFile.WriteString(s)

	if w.truncated {
		return
	}

	remaining := w.limit - w.written
	if len(s) <= remaining {
		fmt.Print(s)
		w.written += len(s)
	} else {
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
		if w.tmpFile != nil {
			_ = w.tmpFile.Close()
			_ = os.Remove(w.tmpFile.Name())
		}
		fmt.Println()
		return
	}

	// Close the temp file so it's readable
	tmpPath := w.tmpFile.Name()
	_ = w.tmpFile.Close()

	fmt.Printf("\n\n--- response truncated (%d bytes total) ---\n", w.totalBytes)
	fmt.Printf("Full response: %s\n", tmpPath)
	fmt.Printf("Explore:\n")
	fmt.Printf("  cat %s | grep \"<pattern>\"\n", tmpPath)
	fmt.Printf("  cat %s | tail -50\n", tmpPath)
}
