package cmd

import (
	"bufio"
	"bytes"
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
	"github.com/onyx-dot-app/onyx/cli/internal/parser"
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
prompts for each one; answer d to show all arguments in full. Without a
terminal, or with --json, it never waits: --approve sets the answer. After
the decisions, ask follows the response to its answer. The default, fail,
rejects the tool call, lets the response finish without it, and exits with
code 10. An interrupt at a prompt exits with code 11 and leaves the request
waiting for another client.`,
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
			// The terminal behind promptReader, when it is a file.
			var promptTerminal *os.File
			if !askJSON && !cmd.Flags().Changed("approve") && ios.IsStderrTTY && os.Getenv("CI") == "" {
				if ios.IsStdinTTY {
					promptReader = bufio.NewReader(ios.In)
					promptTerminal, _ = ios.In.(*os.File)
				} else if tty, err := iostreams.OpenTerminalInput(); err == nil {
					defer func() { _ = tty.Close() }()
					promptReader = bufio.NewReader(tty)
					promptTerminal = tty
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
			// The response that the message started.
			var responseID int
			// The stream that ch reads.
			var streamID int
			// The cursor after the last complete batch of streamID, and the
			// cursor that ch resumed it from.
			cursor, resumedFrom := 0, 0
			var lastErr error
			gotStop := false
			// The stream stopped while the response waits for decisions.
			awaiting := false
			// The stream that a decision named to continue the response.
			var continuation *models.ChatStream
			// A continuation first replays the response from its start. ask
			// drops the replay up to its end marker, so it shows nothing twice.
			replaying := false
			// The server has no buffer for the stream that ch reads.
			unavailable := false
			// ch reads the saved response, not a stream.
			fromSaved := false
			// The answer text shown so far, as the saved response renders it: a
			// continuation's replay of the saved response replaces the live text
			// up to its end marker.
			var answer strings.Builder
			// The text of the replay that the current continuation sends.
			var replayed strings.Builder
			// approvalErr ends the run after a decision failed. The owner of a
			// running stream stops its response; a waiting response keeps waiting.
			var approvalErr error
			// approvalRequired is the exit after --approve=fail rejected a tool
			// call. The response continues without it first.
			var approvalRequired error
			// A prompt was interrupted before its decision.
			undecided := false
			// The titles of the requests shown here, by approval id.
			asked := map[string]string{}
			// Requests whose outcome was shown.
			reported := map[string]bool{}
			// Events that arrived while a prompt waited, handled after it.
			var deferred []models.StreamEvent
			// Requests that the server ended while a prompt waited.
			ended := map[string]bool{}
			// One reader serves every prompt and reads a line only when a prompt
			// asks for one, so a prompt that the stream ended leaves no reader
			// behind. Each line answers only the request whose prompt asked for
			// it, and only input typed after that prompt showed.
			type promptLine struct {
				approvalID string
				text       string
			}
			var promptLines chan promptLine
			// The approval id of the prompt that asks for a line.
			readLine := make(chan string, 1)
			reading := false
			if promptReader != nil {
				promptLines = make(chan promptLine)
				go func() {
					for {
						var approvalID string
						select {
						case approvalID = <-readLine:
						case <-ctx.Done():
							return
						}
						_, _ = promptReader.Discard(promptReader.Buffered())
						if promptTerminal != nil {
							iostreams.DiscardPendingInput(promptTerminal)
						}
						// At end of input every prompt reads "", which rejects.
						line, _ := promptReader.ReadString('\n')
						select {
						case promptLines <- promptLine{approvalID, strings.ToLower(strings.TrimSpace(line))}:
						case <-ctx.Done():
							return
						}
					}
				}()
			}

			// Overflow writer: tees to stdout and optionally to a temp file.
			// In quiet mode, buffer everything and print once at the end.
			ow := &overflow.Writer{Limit: truncateAt, Quiet: askQuiet, Out: ios.Out, ErrOut: ios.ErrOut}

			answerApproval := func(req models.ToolApprovalRequestEvent) {
				title := approval.Title(req)
				if !askJSON {
					if isTTY {
						fmt.Fprintln(ios.ErrOut)
					}
					fmt.Fprintf(ios.ErrOut, "Approval requested: %s\n", title)
					if agent := approval.AgentRequest(req); agent != "" {
						fmt.Fprintf(ios.ErrOut, "  %s\n", agent)
					}
					for _, arg := range approval.Arguments(req.Arguments) {
						fmt.Fprintf(ios.ErrOut, "  %s\n", arg)
					}
				}
				asked[req.ApprovalID] = title
				decision := approveDecision
				if promptLines != nil {
					if ended[req.ApprovalID] {
						// The outer loop reports the queued resolution.
						return
					}
					const promptText = "[y] approve once / [a] approve for session / [d] show all arguments / [N] reject: "
					fmt.Fprint(ios.ErrOut, promptText)
					events := ch
					// After the stream stops, the saved session reports a
					// decision that another client sends.
					var decided chan models.ToolApprovalResolvedEvent
					watchCtx, stopWatch := context.WithCancel(ctx)
					defer stopWatch()
				prompt:
					for {
						if !reading {
							readLine <- req.ApprovalID
							reading = true
						}
						select {
						case <-ctx.Done():
							// A running stream's owner stops its response; a
							// waiting response keeps the request for another client.
							undecided = true
							return
						case event, ok := <-events:
							if !ok {
								// The stream stopped for the decisions; the prompt still waits.
								events = nil
								decided = make(chan models.ToolApprovalResolvedEvent, 1)
								go func() {
									// The approvals version of the last session load.
									version := ""
									for {
										select {
										case <-watchCtx.Done():
											return
										case <-time.After(api.StatusPollInterval):
										}
										status, err := client.ChatSessionStatus(watchCtx, sessionID)
										if err != nil || status.ApprovalsVersion == version {
											continue
										}
										detail, err := client.GetChatSession(watchCtx, sessionID)
										if err != nil {
											continue
										}
										version = detail.ApprovalsVersion
										for _, packets := range detail.Packets {
											for _, packet := range packets {
												if !bytes.Contains(packet, []byte("tool_approval_resolved")) {
													continue
												}
												if e, ok := parser.ParseStreamLine(string(packet)).(models.ToolApprovalResolvedEvent); ok && e.ApprovalID == req.ApprovalID {
													decided <- e
													return
												}
											}
										}
									}
								}()
								continue
							}
							deferred = append(deferred, event)
							if resolved, isResolved := event.(models.ToolApprovalResolvedEvent); isResolved {
								ended[resolved.ApprovalID] = true
							}
							// The server ended the request, e.g. when its program ended.
							if ended[req.ApprovalID] {
								fmt.Fprintln(ios.ErrOut)
								return
							}
						case resolved := <-decided:
							deferred = append(deferred, resolved)
							ended[req.ApprovalID] = true
							fmt.Fprintln(ios.ErrOut)
							return
						case line := <-promptLines:
							reading = false
							if line.approvalID != req.ApprovalID {
								// The line answers a prompt that the server ended.
								fmt.Fprint(ios.ErrOut, promptText)
								continue
							}
							switch line.text {
							case "d":
								fmt.Fprintf(ios.ErrOut, "All arguments of %s:\n", title)
								for _, arg := range approval.AllArguments(req.Arguments) {
									fmt.Fprintf(ios.ErrOut, "  %s\n", arg)
								}
								fmt.Fprint(ios.ErrOut, promptText)
								continue
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
					approvalRequired = exitcodes.Newf(exitcodes.ApprovalRequired,
						"tool call %q needed approval, so ask rejected it; rerun on a terminal, or with --approve=once, --approve=session, or --approve=reject", title)
				}
				result, err := client.DecideApproval(ctx, req.ApprovalID, decision)
				switch {
				case ctx.Err() != nil:
				case err == nil:
					if result.Continuation != nil {
						continuation = result.Continuation
					}
				case api.IsApprovalNoLongerWaiting(err):
					if !askJSON {
						fmt.Fprintf(ios.ErrOut, "%s: %s\n", approval.NoLongerWaiting, title)
					}
				default:
					if approvalErr == nil {
						approvalErr = apiErrorToExit(err, "cannot send the approval decision")
					}
					cancelStream()
				}
			}

			for {
				for {
					var event models.StreamEvent
					if len(deferred) > 0 {
						event, deferred = deferred[0], deferred[1:]
					} else if next, ok := <-ch; ok {
						event = next
					} else {
						break
					}
					if approvalErr != nil || undecided {
						// Drain so the stream owner can stop the turn before exit.
						if stop, ok := event.(models.StopEvent); ok {
							awaiting = stop.AwaitingApproval()
						}
						continue
					}
					if e, ok := event.(models.StreamCursorEvent); ok {
						streamID, cursor = e.StreamID, e.NextCursor
						continue
					}
					if replaying {
						switch e := event.(type) {
						case models.ReplayEndEvent:
							replaying = false
							answer.Reset()
							answer.WriteString(replayed.String())
							replayed.Reset()
							continue
						case models.MessageDeltaEvent:
							replayed.WriteString(e.Content)
							continue
						case models.ErrorEvent, models.StreamUnavailableEvent:
						case models.ToolApprovalResolvedEvent:
							// The outcome of a request asked here can be in the replay.
							if _, waited := asked[e.ApprovalID]; !waited {
								continue
							}
						default:
							continue
						}
					}
					switch e := event.(type) {
					case models.SessionCreatedEvent:
						sessionID = e.ChatSessionID
					case models.MessageIDEvent:
						streamID = e.ReservedAgentMessageID
						responseID = e.ReservedAgentMessageID
					case models.StreamUnavailableEvent:
						unavailable = true
						continue
					case models.MessageDeltaEvent:
						answer.WriteString(e.Content)
					case models.StopEvent:
						// Keep draining: the server saves the turn after it sends stop,
						// and the rename below reads the saved history.
						gotStop = true
						awaiting = e.AwaitingApproval()
					case models.ToolApprovalRequestEvent:
						if _, seen := asked[e.ApprovalID]; seen {
							continue
						}
					case models.ToolApprovalResolvedEvent:
						if reported[e.ApprovalID] {
							continue
						}
						reported[e.ApprovalID] = true
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
							answerApproval(req)
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
						answerApproval(e)
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
				// The stream closed before its stop, for example when the
				// server's buffer for it ended.
				interrupted := !gotStop && !unavailable && responseID != 0
				if (!awaiting && !unavailable && !interrupted) || approvalErr != nil || lastErr != nil || ctx.Err() != nil {
					break
				}
				// The response continues on the stream that a decision named.
				// Otherwise the status names the stream that continues it, for
				// example after a decision while the response still ran.
				next := continuation
				continuation = nil
				if next != nil && next.StreamID == streamID {
					next = nil
				}
				if next == nil && interrupted && !fromSaved && cursor > resumedFrom {
					// The stream continues after its last complete batch.
					resumedFrom = cursor
					ch = client.ResumeChatStream(streamCtx, sessionID, &streamID, cursor)
					continue
				}
				if next == nil {
					followed, err := api.FollowResponse(ctx, client, sessionID, responseID, streamID)
					if ctx.Err() != nil {
						break
					}
					if err != nil {
						return fmt.Errorf("cannot follow the response after the approval decisions: %w", err)
					}
					next = followed
				}
				if next != nil {
					streamID = next.StreamID
					ch = client.ResumeChatStream(streamCtx, sessionID, &streamID, 0)
					cursor, resumedFrom = 0, 0
					replaying, fromSaved = true, false
					gotStop, awaiting, unavailable = false, false, false
					continue
				}
				if fromSaved {
					return exitcodes.New(exitcodes.General, "the response did not continue after the approval decisions; open the chat to see it")
				}
				// No stream continues the response: the saved session shows how
				// it went on, with the requests it still waits for.
				detail, err := client.GetChatSession(ctx, sessionID)
				if ctx.Err() != nil {
					break
				}
				if err != nil {
					return fmt.Errorf("cannot load the response after the approval decisions: %w", err)
				}
				assistant := 0
				for _, message := range detail.Messages {
					if message.MessageType != "assistant" {
						continue
					}
					if message.MessageID == responseID && assistant < len(detail.Packets) {
						// The saved packets render the response as a replay does,
						// so the text that ask showed is their prefix.
						var saved strings.Builder
						// Like a stream, ask shows only the response's own requests.
						requested := map[string]bool{}
						var events []models.StreamEvent
						for _, packet := range detail.Packets[assistant] {
							switch e := parser.ParseStreamLine(string(packet)).(type) {
							case models.MessageDeltaEvent:
								saved.WriteString(e.Content)
							case models.ToolApprovalRequestEvent:
								if e.AgentName == "" {
									requested[e.ApprovalID] = true
									events = append(events, e)
								}
							case models.ToolApprovalResolvedEvent:
								if requested[e.ApprovalID] {
									events = append(events, e)
								}
							case models.StopEvent:
								events = append(events, e)
							}
						}
						if rest, shown := strings.CutPrefix(saved.String(), answer.String()); !shown {
							fmt.Fprintln(ios.ErrOut, "warning: the saved answer differs from the text shown; open the chat to see all of it")
						} else if rest != "" {
							deferred = append(deferred, models.MessageDeltaEvent{Content: rest})
						}
						deferred = append(deferred, events...)
						if message.Error != nil {
							deferred = append(deferred, models.ErrorEvent{Error: *message.Error})
						}
					}
					assistant++
				}
				if len(deferred) == 0 {
					return exitcodes.New(exitcodes.General, "the response did not continue after the approval decisions; open the chat to see it")
				}
				saved := make(chan models.StreamEvent)
				close(saved)
				ch = saved
				replaying, fromSaved = false, true
				gotStop, awaiting, unavailable = false, false, false
			}

			if !askJSON {
				ow.Finish()
			}

			if approvalErr != nil {
				return approvalErr
			}
			if ctx.Err() != nil {
				if awaiting && undecided {
					return exitcodes.New(exitcodes.ApprovalPending,
						"interrupted while a tool call waits for approval; it still waits, and another Onyx client can decide it")
				}
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
			return approvalRequired
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
