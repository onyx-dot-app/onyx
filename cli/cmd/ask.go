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
			var prompt *terminalPrompt
			if !askJSON && !cmd.Flags().Changed("approve") && ios.IsStderrTTY && os.Getenv("CI") == "" {
				if ios.IsStdinTTY {
					terminal, _ := ios.In.(*os.File)
					prompt = newTerminalPrompt(ctx, bufio.NewReader(ios.In), terminal)
				} else if tty, err := iostreams.OpenTerminalInput(); err == nil {
					defer func() { _ = tty.Close() }()
					prompt = newTerminalPrompt(ctx, bufio.NewReader(tty), tty)
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

			run := &askRun{
				ctx:             ctx,
				streamCtx:       streamCtx,
				cancelStream:    cancelStream,
				ios:             ios,
				client:          client,
				json:            askJSON,
				quiet:           askQuiet,
				isTTY:           isTTY,
				approveDecision: approveDecision,
				failOnApproval:  askApprove == "fail",
				prompt:          prompt,
				// Tees to stdout and optionally to a temp file. In quiet mode,
				// it buffers everything and prints once at the end.
				ow:       &overflow.Writer{Limit: truncateAt, Quiet: askQuiet, Out: ios.Out, ErrOut: ios.ErrOut},
				ch:       ch,
				asked:    map[string]string{},
				reported: map[string]bool{},
				ended:    map[string]bool{},
			}
			for {
				for {
					var event models.StreamEvent
					if len(run.deferred) > 0 {
						event, run.deferred = run.deferred[0], run.deferred[1:]
					} else if next, ok := <-run.ch; ok {
						event = next
					} else {
						break
					}
					if err := run.handle(event); err != nil {
						return err
					}
				}
				more, err := run.continueResponse()
				if err != nil {
					return err
				}
				if !more {
					break
				}
			}
			return run.result()
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

// askRun is the state of one ask command: the stream that it reads, the
// answer that it showed, and the approval requests that it handled.
type askRun struct {
	ctx context.Context
	// streamCtx and cancelStream bound the streams that ch reads.
	streamCtx    context.Context
	cancelStream context.CancelFunc
	ios          *iostreams.IOStreams
	client       *api.Client
	json         bool
	quiet        bool
	isTTY        bool
	// approveDecision answers requests when no terminal prompts.
	approveDecision models.ApprovalDecision
	// failOnApproval makes a rejected request end the run with exit code 10.
	failOnApproval bool
	// prompt asks the person at the terminal, or nil.
	prompt *terminalPrompt
	ow     *overflow.Writer
	// ch is the stream, or the saved response, that the run reads.
	ch        <-chan models.StreamEvent
	sessionID string
	// The response that the message started.
	responseID int
	// The stream that ch reads.
	streamID int
	// The cursor after the last complete batch of streamID, and the cursor
	// that ch resumed it from.
	cursor, resumedFrom int
	lastErr             error
	gotStop             bool
	// The stream stopped while the response waits for decisions.
	awaiting bool
	// The stream that a decision named to continue the response.
	continuation *models.ChatStream
	// A continuation first replays the response from its start. ask drops
	// the replay up to its end marker, so it shows nothing twice.
	replaying bool
	// The server has no buffer for the stream that ch reads.
	unavailable bool
	// ch reads the saved response, not a stream, and no decision was sent
	// since; another load of the saved response would show nothing new.
	fromSaved bool
	// The answer text shown so far, as the saved response renders it: a
	// continuation's replay of the saved response replaces the live text up
	// to its end marker.
	answer strings.Builder
	// The text of the replay that the current continuation sends.
	replayed strings.Builder
	// approvalErr ends the run after a decision failed. The owner of a
	// running stream stops its response; a waiting response keeps waiting.
	approvalErr error
	// approvalRequired is the exit after --approve=fail rejected a tool
	// call. The response continues without it first.
	approvalRequired error
	// A prompt was interrupted before its decision.
	undecided bool
	// The titles of the requests shown here, by approval id.
	asked map[string]string
	// Requests whose outcome was shown.
	reported map[string]bool
	// Events that arrived while a prompt waited, handled after it.
	deferred []models.StreamEvent
	// Requests that the server ended while a prompt waited.
	ended map[string]bool
}

// handle applies one event to the run and shows it. It returns the error
// that ends the run.
func (r *askRun) handle(event models.StreamEvent) error {
	if r.approvalErr != nil || r.undecided {
		// Drain so the stream owner can stop the turn before exit.
		if stop, ok := event.(models.StopEvent); ok {
			r.awaiting = stop.AwaitingApproval()
		}
		return nil
	}
	if e, ok := event.(models.StreamCursorEvent); ok {
		r.streamID, r.cursor = e.StreamID, e.NextCursor
		return nil
	}
	if r.replaying {
		switch e := event.(type) {
		case models.ReplayEndEvent:
			r.replaying = false
			r.answer.Reset()
			r.answer.WriteString(r.replayed.String())
			r.replayed.Reset()
			return nil
		case models.MessageDeltaEvent:
			r.replayed.WriteString(e.Content)
			return nil
		case models.ErrorEvent, models.StreamUnavailableEvent:
		case models.ToolApprovalResolvedEvent:
			// The outcome of a request asked here can be in the replay.
			if _, waited := r.asked[e.ApprovalID]; !waited {
				return nil
			}
		default:
			return nil
		}
	}
	switch e := event.(type) {
	case models.SessionCreatedEvent:
		r.sessionID = e.ChatSessionID
	case models.MessageIDEvent:
		r.streamID = e.ReservedAgentMessageID
		r.responseID = e.ReservedAgentMessageID
	case models.StreamUnavailableEvent:
		r.unavailable = true
		return nil
	case models.MessageDeltaEvent:
		r.answer.WriteString(e.Content)
	case models.StopEvent:
		// Keep draining: the server saves the turn after it sends stop, and
		// the rename after the run reads the saved history.
		r.gotStop = true
		r.awaiting = e.AwaitingApproval()
	case models.ToolApprovalRequestEvent:
		if _, seen := r.asked[e.ApprovalID]; seen {
			return nil
		}
	case models.ToolApprovalResolvedEvent:
		if r.reported[e.ApprovalID] {
			return nil
		}
		r.reported[e.ApprovalID] = true
	}
	if r.json {
		return r.emitJSON(event)
	}
	return r.render(event)
}

// emitJSON writes event as an NDJSON line and answers a request that it
// carries. An error event becomes the run's exit.
func (r *askRun) emitJSON(event models.StreamEvent) error {
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
	fmt.Fprintln(r.ios.Out, string(data))
	if req, ok := event.(models.ToolApprovalRequestEvent); ok {
		r.answerApproval(req)
	}
	if errEvt, ok := event.(models.ErrorEvent); ok {
		if errEvt.StatusCode != 0 {
			r.lastErr = exitcodes.Newf(exitcodes.ForHTTPStatus(errEvt.StatusCode), "%s", sanitize.Terminal(errEvt.Error))
		} else {
			r.lastErr = exitcodes.New(exitcodes.General, sanitize.Terminal(errEvt.Error))
		}
	}
	return nil
}

// render shows event as text: the answer on stdout, and progress, approval
// requests and outcomes on stderr. An error event ends the run.
func (r *askRun) render(event models.StreamEvent) error {
	ios := r.ios
	progress := r.isTTY && !r.quiet
	switch e := event.(type) {
	case models.MessageDeltaEvent:
		r.ow.Write(sanitize.Terminal(e.Content))
	case models.SearchStartEvent:
		if progress {
			if e.IsInternetSearch {
				fmt.Fprintf(ios.ErrOut, "\033[2mSearching the web...\033[0m\n")
			} else {
				fmt.Fprintf(ios.ErrOut, "\033[2mSearching documents...\033[0m\n")
			}
		}
	case models.SearchQueriesEvent:
		if progress {
			for _, q := range e.Queries {
				fmt.Fprintf(ios.ErrOut, "\033[2m  → %s\033[0m\n", sanitize.Terminal(q))
			}
		}
	case models.SearchDocumentsEvent:
		if progress && len(e.Documents) > 0 {
			fmt.Fprintf(ios.ErrOut, "\033[2mFound %d documents\033[0m\n", len(e.Documents))
		}
	case models.ReasoningStartEvent:
		if progress {
			fmt.Fprintf(ios.ErrOut, "\033[2mThinking...\033[0m\n")
		}
	case models.ToolStartEvent:
		if progress && e.ToolName != "" {
			fmt.Fprintf(ios.ErrOut, "\033[2mUsing %s...\033[0m\n", sanitize.Terminal(e.ToolName))
		}
	case models.ToolApprovalRequestEvent:
		r.answerApproval(e)
	case models.ToolApprovalResolvedEvent:
		if title, ok := r.asked[e.ApprovalID]; ok {
			fmt.Fprintf(ios.ErrOut, "%s: %s\n", approval.OutcomeLabel(e.Outcome), title)
		}
	case models.ErrorEvent:
		r.ow.Finish()
		if e.StatusCode != 0 {
			return exitcodes.Newf(exitcodes.ForHTTPStatus(e.StatusCode), "%s", sanitize.Terminal(e.Error))
		}
		return exitcodes.New(exitcodes.General, sanitize.Terminal(e.Error))
	}
	return nil
}

// answerApproval shows a request, gets its answer from the terminal or from
// --approve, and sends the decision.
func (r *askRun) answerApproval(req models.ToolApprovalRequestEvent) {
	ios := r.ios
	title := approval.Title(req)
	if !r.json {
		if r.isTTY {
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
	r.asked[req.ApprovalID] = title
	decision := r.approveDecision
	if p := r.prompt; p != nil {
		if r.ended[req.ApprovalID] {
			// The outer loop reports the queued resolution.
			return
		}
		const promptText = "[y] approve once / [a] approve for session / [d] show all arguments / [N] reject: "
		fmt.Fprint(ios.ErrOut, promptText)
		events := r.ch
		// After the stream stops, the saved session reports a decision that
		// another client sends.
		var decided <-chan models.ToolApprovalResolvedEvent
		watchCtx, stopWatch := context.WithCancel(r.ctx)
		defer stopWatch()
	prompt:
		for {
			if !p.reading {
				p.readLine <- req.ApprovalID
				p.reading = true
			}
			select {
			case <-r.ctx.Done():
				// A running stream's owner stops its response; a waiting
				// response keeps the request for another client.
				r.undecided = true
				return
			case event, ok := <-events:
				if !ok {
					// The stream stopped for the decisions; the prompt still waits.
					events = nil
					decided = watchSavedDecision(watchCtx, r.client, r.sessionID, req.ApprovalID)
					continue
				}
				r.deferred = append(r.deferred, event)
				if resolved, isResolved := event.(models.ToolApprovalResolvedEvent); isResolved {
					r.ended[resolved.ApprovalID] = true
				}
				// The server ended the request, e.g. when its program ended.
				if r.ended[req.ApprovalID] {
					fmt.Fprintln(ios.ErrOut)
					return
				}
			case resolved := <-decided:
				r.deferred = append(r.deferred, resolved)
				r.ended[req.ApprovalID] = true
				// The decision lets the response go on, also as saved.
				r.fromSaved = false
				fmt.Fprintln(ios.ErrOut)
				return
			case line := <-p.lines:
				p.reading = false
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
	if r.prompt == nil && r.failOnApproval {
		r.approvalRequired = exitcodes.Newf(exitcodes.ApprovalRequired,
			"tool call %q needed approval, so ask rejected it; rerun on a terminal, or with --approve=once, --approve=session, or --approve=reject", title)
	}
	result, err := r.client.DecideApproval(r.ctx, req.ApprovalID, decision)
	switch {
	case r.ctx.Err() != nil:
	case err == nil:
		if result.Continuation != nil {
			r.continuation = result.Continuation
		}
		// The decision lets the response go on, also as saved.
		r.fromSaved = false
	case api.IsApprovalNoLongerWaiting(err):
		r.fromSaved = false
		if !r.json {
			fmt.Fprintf(ios.ErrOut, "%s: %s\n", approval.NoLongerWaiting, title)
		}
	default:
		if r.approvalErr == nil {
			r.approvalErr = apiErrorToExit(err, "cannot send the approval decision")
		}
		r.cancelStream()
	}
}

// continueResponse decides how the response goes on after ch closed: after
// the last complete batch of its stream, on the stream that a decision or
// the status names, or as the saved session shows. It reports false when the
// run reads nothing more.
func (r *askRun) continueResponse() (bool, error) {
	// The stream closed before its stop, for example when the server's
	// buffer for it ended.
	interrupted := !r.gotStop && !r.unavailable && r.responseID != 0
	if (!r.awaiting && !r.unavailable && !interrupted) || r.approvalErr != nil || r.lastErr != nil || r.ctx.Err() != nil {
		return false, nil
	}
	// The response continues on the stream that a decision named.
	// Otherwise the status names the stream that continues it, for example
	// after a decision while the response still ran.
	next := r.continuation
	r.continuation = nil
	if next != nil && next.StreamID == r.streamID {
		next = nil
	}
	if next == nil && interrupted && !r.fromSaved && r.cursor > r.resumedFrom {
		// The stream continues after its last complete batch.
		r.resumedFrom = r.cursor
		r.ch = r.client.ResumeChatStream(r.streamCtx, r.sessionID, &r.streamID, r.cursor)
		return true, nil
	}
	if next == nil {
		followed, err := api.FollowResponse(r.ctx, r.client, r.sessionID, r.responseID, r.streamID)
		if r.ctx.Err() != nil {
			return false, nil
		}
		if err != nil {
			return false, fmt.Errorf("cannot follow the response after the approval decisions: %w", err)
		}
		next = followed
	}
	if next != nil {
		r.streamID = next.StreamID
		r.ch = r.client.ResumeChatStream(r.streamCtx, r.sessionID, &r.streamID, 0)
		r.cursor, r.resumedFrom = 0, 0
		r.replaying, r.fromSaved = true, false
		r.gotStop, r.awaiting, r.unavailable = false, false, false
		return true, nil
	}
	if r.fromSaved {
		return false, exitcodes.New(exitcodes.General, "the response did not continue after the approval decisions; open the chat to see it")
	}
	// No stream continues the response: the saved session shows how it went
	// on, with the requests it still waits for.
	detail, err := r.client.GetChatSession(r.ctx, r.sessionID)
	if r.ctx.Err() != nil {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("cannot load the response after the approval decisions: %w", err)
	}
	events, differs := savedResponseEvents(detail, r.responseID, r.answer.String())
	if differs {
		fmt.Fprintln(r.ios.ErrOut, "warning: the saved answer differs from the text shown; open the chat to see all of it")
	}
	r.deferred = append(r.deferred, events...)
	if len(r.deferred) == 0 {
		return false, exitcodes.New(exitcodes.General, "the response did not continue after the approval decisions; open the chat to see it")
	}
	saved := make(chan models.StreamEvent)
	close(saved)
	r.ch = saved
	r.cursor, r.resumedFrom = 0, 0
	r.replaying, r.fromSaved = false, true
	r.gotStop, r.awaiting, r.unavailable = false, false, false
	return true, nil
}

// result finishes the output and returns the run's exit after the conversation
// is ready, naming a new chat.
func (r *askRun) result() error {
	if !r.json {
		r.ow.Finish()
	}
	if r.approvalErr != nil {
		return r.approvalErr
	}
	if r.ctx.Err() != nil {
		if r.awaiting && r.undecided {
			return exitcodes.New(exitcodes.ApprovalPending,
				"interrupted while a tool call waits for approval; it still waits, and another Onyx client can decide it")
		}
		return nil
	}
	if r.lastErr != nil {
		return r.lastErr
	}
	if !r.gotStop {
		return exitcodes.New(exitcodes.General, "stream ended unexpectedly")
	}
	if r.sessionID != "" {
		readyCtx, readyCancel := context.WithTimeout(r.ctx, 30*time.Second)
		defer readyCancel()
		if err := api.WaitForChatSessionIdle(readyCtx, r.client, r.sessionID); err != nil {
			return fmt.Errorf("cannot confirm conversation readiness: %w", err)
		}
	}
	nameChatSession(r.ctx, r.ios, r.client, r.sessionID)
	return r.approvalRequired
}

// savedResponseEvents renders the saved response responseID as the events
// that ask has not shown: the rest of its text after shown, its own approval
// requests and their outcomes, its stop and its error. differs reports saved
// text that does not start with shown.
func savedResponseEvents(detail *models.ChatSessionDetailResponse, responseID int, shown string) (events []models.StreamEvent, differs bool) {
	assistant := 0
	for _, message := range detail.Messages {
		if message.MessageType != "assistant" {
			continue
		}
		if message.MessageID == responseID && assistant < len(detail.Packets) {
			// The saved packets render the response as a replay does, so the
			// text that ask showed is their prefix.
			var saved strings.Builder
			// Like a stream, ask shows only the response's own requests.
			requested := map[string]bool{}
			var packets []models.StreamEvent
			for _, packet := range detail.Packets[assistant] {
				switch e := parser.ParseStreamLine(string(packet)).(type) {
				case models.MessageDeltaEvent:
					saved.WriteString(e.Content)
				case models.ToolApprovalRequestEvent:
					if e.AgentName == "" {
						requested[e.ApprovalID] = true
						packets = append(packets, e)
					}
				case models.ToolApprovalResolvedEvent:
					if requested[e.ApprovalID] {
						packets = append(packets, e)
					}
				case models.StopEvent:
					packets = append(packets, e)
				}
			}
			if rest, ok := strings.CutPrefix(saved.String(), shown); !ok {
				differs = true
			} else if rest != "" {
				events = append(events, models.MessageDeltaEvent{Content: rest})
			}
			events = append(events, packets...)
			if message.Error != nil {
				events = append(events, models.ErrorEvent{Error: *message.Error})
			}
		}
		assistant++
	}
	return events, differs
}

// promptLine is a line that the terminal read for the prompt of approvalID.
type promptLine struct {
	approvalID string
	text       string
}

// terminalPrompt reads the answers to approval prompts. One reader serves
// every prompt and reads a line only when a prompt asks for one, so a prompt
// that the stream ended leaves no reader behind. Each line answers only the
// request whose prompt asked for it, and only input typed after that prompt
// showed.
type terminalPrompt struct {
	lines chan promptLine
	// readLine carries the approval id of the prompt that asks for a line.
	readLine chan string
	// reading is set from a request for a line until the line arrives.
	reading bool
}

// newTerminalPrompt starts the reader of reader; terminal, when it is a
// file, drops input typed before a prompt showed.
func newTerminalPrompt(ctx context.Context, reader *bufio.Reader, terminal *os.File) *terminalPrompt {
	p := &terminalPrompt{lines: make(chan promptLine), readLine: make(chan string, 1)}
	go func() {
		for {
			var approvalID string
			select {
			case approvalID = <-p.readLine:
			case <-ctx.Done():
				return
			}
			_, _ = reader.Discard(reader.Buffered())
			if terminal != nil {
				iostreams.DiscardPendingInput(terminal)
			}
			// At end of input every prompt reads "", which rejects.
			line, _ := reader.ReadString('\n')
			select {
			case p.lines <- promptLine{approvalID, strings.ToLower(strings.TrimSpace(line))}:
			case <-ctx.Done():
				return
			}
		}
	}()
	return p
}

// watchSavedDecision reads the saved session after each change of its
// approvals version, and delivers the outcome of approvalID once a decision
// that another client sent shows there.
func watchSavedDecision(ctx context.Context, client *api.Client, sessionID, approvalID string) <-chan models.ToolApprovalResolvedEvent {
	decided := make(chan models.ToolApprovalResolvedEvent, 1)
	go func() {
		// The approvals version of the last session load.
		version := ""
		for {
			select {
			case <-ctx.Done():
				return
			case <-time.After(api.StatusPollInterval):
			}
			status, err := client.ChatSessionStatus(ctx, sessionID)
			if err != nil || status.ApprovalsVersion == version {
				continue
			}
			detail, err := client.GetChatSession(ctx, sessionID)
			if err != nil {
				continue
			}
			version = detail.ApprovalsVersion
			for _, packets := range detail.Packets {
				for _, packet := range packets {
					if !bytes.Contains(packet, []byte("tool_approval_resolved")) {
						continue
					}
					if e, ok := parser.ParseStreamLine(string(packet)).(models.ToolApprovalResolvedEvent); ok && e.ApprovalID == approvalID {
						decided <- e
						return
					}
				}
			}
		}
	}()
	return decided
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
