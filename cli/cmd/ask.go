package cmd

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/approval"
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
		askApprove   string
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
to a temp file. Set --max-output 0 to disable truncation.

Some tool calls need your approval before they run. On a terminal, ask
prompts for each one. Without a terminal, or with --json, it never waits:
--approve sets the answer. The default, fail, rejects the tool call and exits
with code 10.`,
		Args: cobra.MaximumNArgs(1),
		Example: `  onyx-cli ask "What connectors are available?"
  onyx-cli ask --agent-id 3 "Summarize our Q4 revenue"
  onyx-cli ask --agent-name "Support Agent" "hello"
  onyx-cli ask --json "List all users" | jq '.event.content'
  cat error.log | onyx-cli ask --prompt "Find the root cause"
  echo "what is onyx?" | onyx-cli ask
  onyx-cli ask --approve=reject "File a ticket for this bug"`,
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg, client, err := requireClient()
			if err != nil {
				return err
			}

			if askJSON && askQuiet {
				return exitcodes.New(exitcodes.BadRequest, "--json and --quiet cannot be used together")
			}
			approveDecision, validApprove := map[string]models.ApprovalDecision{
				"fail":    models.RejectApproval,
				"reject":  models.RejectApproval,
				"once":    models.ApproveOnce,
				"session": models.ApproveSession,
			}[askApprove]
			if !validApprove {
				return exitcodes.Newf(exitcodes.BadRequest, "--approve must be fail, reject, once, or session, not %q", askApprove)
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

			// A person answers approval prompts on a terminal. Scripts, agents,
			// CI and --json get the --approve answer instead and never block.
			var promptReader *bufio.Reader
			if !askJSON && !cmd.Flags().Changed("approve") && ios.IsStderrTTY && os.Getenv("CI") == "" {
				if ios.IsStdinTTY {
					promptReader = bufio.NewReader(ios.In)
				} else if tty, err := os.Open("/dev/tty"); err == nil {
					defer func() { _ = tty.Close() }()
					promptReader = bufio.NewReader(tty)
				}
			}

			streamCtx, cancelStream := context.WithCancel(ctx)
			defer cancelStream()
			parentID := -1
			ch := client.SendMessageStream(
				streamCtx,
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
			// approvalErr ends the run after --approve=fail rejected a tool call.
			var approvalErr error
			// The titles of the requests shown here, by approval id.
			asked := map[string]string{}
			// Events that arrived while a prompt waited, handled after it.
			var deferred []models.StreamEvent
			// One reader serves every prompt and reads a line only when a prompt
			// asks for one, so a prompt that the stream ended leaves no reader
			// behind. A line read before a prompt showed answers an earlier one.
			type promptLine struct {
				text string
				at   time.Time
			}
			var promptLines chan promptLine
			readLine := make(chan struct{}, 1)
			reading := false
			if promptReader != nil {
				promptLines = make(chan promptLine)
				go func() {
					for {
						select {
						case <-readLine:
						case <-ctx.Done():
							return
						}
						// At end of input every prompt reads "", which rejects.
						line, _ := promptReader.ReadString('\n')
						select {
						case promptLines <- promptLine{strings.ToLower(strings.TrimSpace(line)), time.Now()}:
						case <-ctx.Done():
							return
						}
					}
				}()
			}

			// Overflow writer: tees to stdout and optionally to a temp file.
			// In quiet mode, buffer everything and print once at the end.
			ow := &overflow.Writer{Limit: truncateAt, Quiet: askQuiet, Out: ios.Out, ErrOut: ios.ErrOut}

			answerApproval := func(req models.ToolApprovalRequestEvent) error {
				title := approval.Title(req)
				if !askJSON {
					if isTTY {
						fmt.Fprintln(ios.ErrOut)
					}
					fmt.Fprintf(ios.ErrOut, "Approval requested: %s\n", title)
					for _, arg := range approval.Arguments(req.Arguments) {
						fmt.Fprintf(ios.ErrOut, "  %s\n", arg)
					}
					if deadline := approval.Deadline(req.ExpiresAt); deadline != "" {
						fmt.Fprintf(ios.ErrOut, "  %s\n", deadline)
					}
				}
				asked[req.ApprovalID] = title
				decision := approveDecision
				if promptLines != nil {
					fmt.Fprint(ios.ErrOut, "[y] approve once / [a] approve for session / [N] reject: ")
					shownAt := time.Now()
				prompt:
					for {
						if !reading {
							readLine <- struct{}{}
							reading = true
						}
						select {
						case <-ctx.Done():
							// Interrupted: stream cancellation stops the turn.
							return nil
						case event, ok := <-ch:
							if !ok {
								fmt.Fprintln(ios.ErrOut)
								return nil
							}
							deferred = append(deferred, event)
							// The server ended the request, e.g. at its deadline.
							if resolved, isResolved := event.(models.ToolApprovalResolvedEvent); isResolved && resolved.ApprovalID == req.ApprovalID {
								fmt.Fprintln(ios.ErrOut)
								return nil
							}
						case line := <-promptLines:
							reading = false
							if line.at.Before(shownAt) {
								continue
							}
							switch line.text {
							case "y", "yes":
								decision = models.ApproveOnce
							case "a":
								decision = models.ApproveSession
							default:
								decision = models.RejectApproval
							}
							break prompt
						}
					}
				}
				if promptReader == nil && askApprove == "fail" {
					approvalErr = exitcodes.Newf(exitcodes.ApprovalRequired,
						"tool call %q needs approval; rerun on a terminal, or with --approve=once, --approve=session, or --approve=reject", title)
					// The rejected turn would continue without the tool; stop it.
					defer cancelStream()
				}
				_, err := client.DecideApproval(ctx, req.ApprovalID, decision)
				switch {
				case err == nil || ctx.Err() != nil:
					return nil
				case api.IsApprovalNoLongerWaiting(err):
					if !askJSON {
						fmt.Fprintf(ios.ErrOut, "%s: %s\n", approval.NoLongerWaiting, title)
					}
					return nil
				default:
					return apiErrorToExit(err, "cannot send the approval decision")
				}
			}

			for {
				var event models.StreamEvent
				if len(deferred) > 0 {
					event, deferred = deferred[0], deferred[1:]
				} else if next, ok := <-ch; ok {
					event = next
				} else {
					break
				}
				if approvalErr != nil {
					// Drain so the stream owner can stop the turn before exit.
					continue
				}
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
					if req, ok := event.(models.ToolApprovalRequestEvent); ok {
						if err := answerApproval(req); err != nil {
							return err
						}
					}
					if errEvt, ok := event.(models.ErrorEvent); ok {
						if errEvt.StatusCode != 0 {
							lastErr = exitcodes.Newf(exitcodes.ForHTTPStatus(errEvt.StatusCode), "%s", sanitize.Terminal(errEvt.Error))
						} else {
							lastErr = exitcodes.New(exitcodes.General, sanitize.Terminal(errEvt.Error))
						}
					}
					continue
				}

				switch e := event.(type) {
				case models.MessageDeltaEvent:
					ow.Write(sanitize.Terminal(e.Content))
				case models.SearchStartEvent:
					if isTTY && !askQuiet {
						if e.IsInternetSearch {
							fmt.Fprintf(ios.ErrOut, "\033[2mSearching the web...\033[0m\n")
						} else {
							fmt.Fprintf(ios.ErrOut, "\033[2mSearching documents...\033[0m\n")
						}
					}
				case models.SearchQueriesEvent:
					if isTTY && !askQuiet {
						for _, q := range e.Queries {
							fmt.Fprintf(ios.ErrOut, "\033[2m  → %s\033[0m\n", sanitize.Terminal(q))
						}
					}
				case models.SearchDocumentsEvent:
					if isTTY && !askQuiet && len(e.Documents) > 0 {
						fmt.Fprintf(ios.ErrOut, "\033[2mFound %d documents\033[0m\n", len(e.Documents))
					}
				case models.ReasoningStartEvent:
					if isTTY && !askQuiet {
						fmt.Fprintf(ios.ErrOut, "\033[2mThinking...\033[0m\n")
					}
				case models.ToolStartEvent:
					if isTTY && !askQuiet && e.ToolName != "" {
						fmt.Fprintf(ios.ErrOut, "\033[2mUsing %s...\033[0m\n", sanitize.Terminal(e.ToolName))
					}
				case models.ToolApprovalRequestEvent:
					if err := answerApproval(e); err != nil {
						ow.Finish()
						return err
					}
				case models.ToolApprovalResolvedEvent:
					if title, ok := asked[e.ApprovalID]; ok {
						fmt.Fprintf(ios.ErrOut, "%s: %s\n", approval.OutcomeLabel(e.Outcome), title)
					}
				case models.ErrorEvent:
					ow.Finish()
					if e.StatusCode != 0 {
						return exitcodes.Newf(exitcodes.ForHTTPStatus(e.StatusCode), "%s", sanitize.Terminal(e.Error))
					}
					return exitcodes.New(exitcodes.General, sanitize.Terminal(e.Error))
				}
			}

			if !askJSON {
				ow.Finish()
			}

			if approvalErr != nil {
				return approvalErr
			}
			if ctx.Err() != nil {
				return nil
			}

			if lastErr != nil {
				return lastErr
			}
			if !gotStop {
				return exitcodes.New(exitcodes.General, "stream ended unexpectedly")
			}
			if sessionID != "" {
				readyCtx, readyCancel := context.WithTimeout(ctx, 30*time.Second)
				defer readyCancel()
				if err := api.WaitForChatSessionIdle(readyCtx, client, sessionID); err != nil {
					return fmt.Errorf("cannot confirm conversation readiness: %w", err)
				}
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
	cmd.Flags().StringVar(&askApprove, "approve", "fail",
		"Answer to tool approval requests when ask cannot prompt: fail (reject and exit 10), reject, once, or session")
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
