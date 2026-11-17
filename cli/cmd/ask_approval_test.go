package cmd

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

// approvalRun is what the fake server saw during one ask run.
type approvalRun struct {
	// decisions receives "id:decision" for each decision.
	decisions chan string
	// stops receives the stream_id of each Stop.
	stops chan string
	// sent closes when the server finished the stream of the message.
	sent chan struct{}
	// decideElsewhere decides a request as another client does.
	decideElsewhere func(id, outcome string)
}

// within receives from ch, or fails the test after five seconds.
func within[T any](t *testing.T, ch <-chan T) T {
	t.Helper()
	select {
	case value := <-ch:
		return value
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for the run")
		var zero T
		return zero
	}
}

// approvalServerOptions changes how the fake server answers.
type approvalServerOptions struct {
	// The decision endpoint's status.
	decisionStatus int
	// The tool is disabled by a policy, so an approval rejects it.
	disabled bool
	// The approval ids of the response's requests; "a1" when empty.
	requests []string
	// A foreground child also asks, as c1, before the search starts. The
	// continuation replays c1's outcome, since the child does not wait.
	childRequest bool
	// The server has no buffer for the continuation, and the saved session
	// shows the finished answer.
	unbuffered bool
	// The continuation fails after its replay, before the run starts.
	resumeFails bool
	// The continuation writes more text, then asks again, as a9. The
	// decision names stream 4, which has no buffer, so the saved session
	// finishes the answer.
	asksAgain bool
	// The continuation closes after its replay without a stop; a resume
	// from its cursor finishes the answer.
	interrupted bool
	// Another client decides; the status names the continuation and a new
	// approvals version.
	decidedElsewhere bool
	// The saved session cannot load.
	savedFails bool
}

// newApprovalServer streams some text and the response's tool approval
// requests, then stops for the decisions. The decision that decides the last
// request names stream 3 as the continuation; after a decision that another
// client made, the status names it. Stream 3 replays the response from its
// start, with text that differs from the live text, up to its replay end
// marker. Then it resolves the requests and finishes the answer.
func newApprovalServer(t *testing.T, opts approvalServerOptions) *approvalRun {
	t.Helper()
	if opts.decisionStatus == 0 {
		opts.decisionStatus = http.StatusOK
	}
	if len(opts.requests) == 0 {
		opts.requests = []string{"a1"}
	}
	run := &approvalRun{decisions: make(chan string, 8), stops: make(chan string, 8), sent: make(chan struct{})}
	requests := make([]map[string]any, len(opts.requests))
	for i, id := range opts.requests {
		requests[i] = requestEvent(id)
	}
	requests[0]["display_name"] = "Create issue"
	requests[0]["arguments"] = map[string]any{"title": "Bug\x1b]52;c;ZWNobyBoaQ==\x07 report"}
	child := requestEvent("c1")
	all := requests
	if opts.childRequest {
		all = append([]map[string]any{child}, requests...)
	}
	var mu sync.Mutex
	// The outcome of each decided request, by approval id.
	outcomes := map[string]string{}
	continuing := false
	run.decideElsewhere = func(id, outcome string) {
		mu.Lock()
		defer mu.Unlock()
		outcomes[id] = outcome
		continuing = len(outcomes) == len(all)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/api/chat/send-chat-message", func(w http.ResponseWriter, r *http.Request) {
		defer close(run.sent)
		fmt.Fprintf(w, "{\"chat_session_id\":%q}\n", testSessionID)
		fmt.Fprintln(w, `{"user_message_id":1,"reserved_assistant_message_id":2}`)
		fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "Filing. "}))
		if opts.childRequest {
			fmt.Fprintln(w, streamLine("tool_approval_request", child))
		}
		fmt.Fprintln(w, streamLine("search_tool_start", nil))
		for _, request := range requests {
			fmt.Fprintln(w, streamLine("tool_approval_request", request))
		}
		fmt.Fprintln(w, streamLine("stop", map[string]any{"stop_reason": "awaiting_user"}))
	})
	mux.HandleFunc("POST /api/chat/approvals/{id}/decision", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Decision string `json:"decision"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		id := r.PathValue("id")
		run.decisions <- id + ":" + body.Decision
		outcome, decision, decidedVia := "approved", "APPROVED", "USER"
		switch {
		case opts.decisionStatus != http.StatusOK:
		case body.Decision == "reject":
			outcome, decision = "rejected", "REJECTED"
		case opts.disabled:
			outcome, decision, decidedVia = "disabled", "REJECTED", "POLICY"
		case body.Decision == "approve_session":
			outcome, decidedVia = "approved_for_chat", "SESSION_GRANT"
		}
		mu.Lock()
		outcomes[id] = outcome
		continuing = len(outcomes) == len(all)
		mu.Unlock()
		if opts.decisionStatus != http.StatusOK {
			w.WriteHeader(opts.decisionStatus)
			fmt.Fprint(w, `{"error_code":"CONFLICT","detail":"This request was already decided or is no longer waiting"}`)
			return
		}
		continuation := "null"
		if continuing {
			continuation = `{"stream_id":3,"response_ids":[2]}`
		}
		if id == "a9" {
			continuation = `{"stream_id":4,"response_ids":[2]}`
		}
		fmt.Fprintf(w, `{"approval_id":%q,"decision":%q,"decided_via":%q,"continuation":%s}`, id, decision, decidedVia, continuation)
	})
	mux.HandleFunc("/api/chat/chat-session/"+testSessionID+"/status", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		// Only another client's decision leaves the stream to the status.
		if continuing && (opts.decisionStatus != http.StatusOK || opts.decidedElsewhere) && !opts.unbuffered {
			fmt.Fprint(w, `{"is_processing":true,"current_stream":{"stream_id":3,"response_ids":[2]},"approvals_version":"v2"}`)
			return
		}
		fmt.Fprint(w, `{"is_processing":false}`)
	})
	mux.HandleFunc("/api/chat/chat-session/"+testSessionID+"/resume-stream", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		// The cursor after the replay of an interrupted continuation.
		const restCursor = "100"
		cursor := r.URL.Query().Get("cursor")
		rest := opts.interrupted && cursor == restCursor
		if opts.unbuffered || !continuing || r.URL.Query().Get("stream_id") != "3" || (cursor != "0" && !rest) {
			http.NotFound(w, r)
			return
		}
		if rest {
			for _, request := range requests {
				id := request["approval_id"]
				fmt.Fprintln(w, streamLine("tool_approval_resolved", map[string]any{"approval_id": id, "outcome": outcomes[id.(string)]}))
			}
			fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "done"}))
			fmt.Fprintln(w, streamLine("stop", nil))
			fmt.Fprintln(w, `{"stream_id":3,"next_cursor":120,"replay_complete":true}`)
			continuing = false
			return
		}
		fmt.Fprintln(w, `{"stream_id":3,"next_cursor":0,"replay_complete":false}`)
		fmt.Fprintln(w, `{"user_message_id":1,"reserved_assistant_message_id":2}`)
		fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "Filing."}))
		if opts.childRequest {
			fmt.Fprintln(w, streamLine("tool_approval_request", child))
			fmt.Fprintln(w, streamLine("tool_approval_resolved", map[string]any{"approval_id": "c1", "outcome": outcomes["c1"]}))
		}
		fmt.Fprintln(w, streamLine("search_tool_start", nil))
		for _, request := range requests {
			id := request["approval_id"]
			fmt.Fprintln(w, streamLine("tool_approval_request", request))
			fmt.Fprintln(w, streamLine("tool_approval_resolved", map[string]any{"approval_id": id, "outcome": outcomes[id.(string)]}))
		}
		fmt.Fprintln(w, streamLine("replay_end", nil))
		if opts.interrupted {
			// The buffer breaks after this batch.
			fmt.Fprintf(w, "{\"stream_id\":3,\"next_cursor\":%s,\"replay_complete\":true}\n", restCursor)
			return
		}
		if opts.resumeFails {
			fmt.Fprintln(w, streamLine("error", map[string]any{"exception": "resume failed"}))
			fmt.Fprintln(w, streamLine("stop", nil))
			fmt.Fprintf(w, "{\"stream_id\":3,\"next_cursor\":%d,\"replay_complete\":true}\n", 6+2*len(all))
			continuing = false
			return
		}
		for _, request := range requests {
			id := request["approval_id"]
			fmt.Fprintln(w, streamLine("tool_approval_resolved", map[string]any{"approval_id": id, "outcome": outcomes[id.(string)]}))
		}
		if opts.asksAgain {
			fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "Done"}))
			fmt.Fprintln(w, streamLine("tool_approval_request", requestEvent("a9")))
			fmt.Fprintln(w, streamLine("stop", map[string]any{"stop_reason": "awaiting_user"}))
			fmt.Fprintf(w, "{\"stream_id\":3,\"next_cursor\":%d,\"replay_complete\":true}\n", 9+2*len(all)+len(requests))
			continuing = false
			return
		}
		fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "done"}))
		fmt.Fprintln(w, streamLine("stop", nil))
		fmt.Fprintf(w, "{\"stream_id\":3,\"next_cursor\":%d,\"replay_complete\":true}\n", 7+2*len(all)+len(requests))
		continuing = false
	})
	mux.HandleFunc("/api/chat/get-chat-session/"+testSessionID, func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if opts.savedFails {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		// The saved session renders the response as a continuation's replay
		// does. A response that no stream continued keeps its live text.
		text := []string{"Filing.", "done"}
		switch {
		case opts.unbuffered:
			text = []string{"Filing. ", "done"}
		case opts.asksAgain:
			text = []string{"Filing.", "Done", " filed."}
		}
		var packets []string
		for _, content := range text {
			packets = append(packets, streamLine("message_delta", map[string]any{"content": content}))
		}
		saved := all
		if opts.asksAgain {
			saved = append(slices.Clone(all), requestEvent("a9"))
		}
		for _, request := range saved {
			id := request["approval_id"].(string)
			packets = append(packets, streamLine("tool_approval_request", request))
			if outcome, decided := outcomes[id]; decided {
				packets = append(packets, streamLine("tool_approval_resolved", map[string]any{"approval_id": id, "outcome": outcome}))
			}
		}
		packets = append(packets, streamLine("stop", map[string]any{"stop_reason": "finished"}))
		message, _ := json.Marshal(strings.Join(text, ""))
		fmt.Fprintf(w, `{"chat_session_id":%q,"messages":[{"message_id":1,"message":"file a ticket","message_type":"user"},{"message_id":2,"message":%s,"message_type":"assistant"}],"packets":[[%s]]}`,
			testSessionID, message, strings.Join(packets, ","))
	})
	mux.HandleFunc("/api/chat/stop-chat-session/"+testSessionID, func(w http.ResponseWriter, r *http.Request) {
		run.stops <- r.URL.Query().Get("stream_id")
	})
	mux.HandleFunc("/api/chat/rename-chat-session", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `{"new_name":"Title"}`)
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	testutil.IsolateConfig(t, srv.URL)
	t.Setenv("CI", "")
	return run
}

func runApprovalAsk(t *testing.T, ios *iostreams.IOStreams, args ...string) error {
	t.Helper()
	cmd := newAskCmd(ios)
	cmd.SetArgs(append([]string{"file a ticket"}, args...))
	return cmd.Execute()
}

func exitCode(err error) exitcodes.Code {
	var exitErr *exitcodes.ExitError
	if errors.As(err, &exitErr) {
		return exitErr.Code
	}
	if err != nil {
		return exitcodes.General
	}
	return exitcodes.Success
}

func pipedIOS() (*iostreams.IOStreams, *bytes.Buffer, *bytes.Buffer) {
	out, errOut := &bytes.Buffer{}, &bytes.Buffer{}
	return &iostreams.IOStreams{In: &bytes.Buffer{}, Out: out, ErrOut: errOut, IsStdinTTY: true}, out, errOut
}

// noDecision fails when the server got a decision.
func noDecision(t *testing.T, run *approvalRun) {
	t.Helper()
	select {
	case got := <-run.decisions:
		t.Errorf("sent decision %q", got)
	default:
	}
}

// noStop fails when the server got a Stop.
func noStop(t *testing.T, run *approvalRun) {
	t.Helper()
	select {
	case got := <-run.stops:
		t.Errorf("sent Stop for stream %q", got)
	default:
	}
}

func TestAsk_NonInteractiveRejectsFinishesAndExitsWithApprovalRequired(t *testing.T) {
	run := newApprovalServer(t, approvalServerOptions{requests: []string{"a1", "a2"}})
	ios, out, errOut := pipedIOS()
	err := runApprovalAsk(t, ios)
	if code := exitCode(err); code != exitcodes.ApprovalRequired {
		t.Fatalf("exit code = %d (%v), want %d", code, err, exitcodes.ApprovalRequired)
	}
	if !strings.Contains(err.Error(), "--approve=") {
		t.Errorf("error does not explain how to proceed: %v", err)
	}
	// A waiting response cannot be stopped: each request gets a rejection,
	// and the response finishes without the tools.
	for _, want := range []string{"a1:reject", "a2:reject"} {
		if got := within(t, run.decisions); got != want {
			t.Errorf("decision = %q, want %q", got, want)
		}
	}
	noStop(t, run)
	if out.String() != "Filing. done\n" {
		t.Errorf("stdout = %q, want the finished answer", out.String())
	}
	stderr := errOut.String()
	if !strings.Contains(stderr, "Approval requested: Create issue") || !strings.Contains(stderr, "title: Bug report") {
		t.Errorf("request not printed, stderr = %q", stderr)
	}
	if strings.ContainsAny(stderr, "\x1b\x07") {
		t.Errorf("stderr keeps control characters from model arguments: %q", stderr)
	}
}

func TestAsk_JSONEmitsRequestAndNeverPrompts(t *testing.T) {
	run := newApprovalServer(t, approvalServerOptions{})
	ios, out, _ := pipedIOS()
	ios.IsStderrTTY = true // a terminal does not make --json interactive
	err := runApprovalAsk(t, ios, "--json")
	if code := exitCode(err); code != exitcodes.ApprovalRequired {
		t.Fatalf("exit code = %d (%v), want %d", code, err, exitcodes.ApprovalRequired)
	}
	if got := within(t, run.decisions); got != "a1:reject" {
		t.Errorf("decision = %q", got)
	}
	noStop(t, run)
	var first struct {
		Type  string `json:"type"`
		Event struct {
			ApprovalID string         `json:"approval_id"`
			Arguments  map[string]any `json:"arguments"`
		} `json:"event"`
	}
	for _, line := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		if strings.Contains(line, `"tool_approval_request"`) {
			if err := json.Unmarshal([]byte(line), &first); err != nil {
				t.Fatal(err)
			}
		}
	}
	if first.Type != "tool_approval_request" || first.Event.ApprovalID != "a1" || first.Event.Arguments["title"] == nil {
		t.Fatalf("approval request not emitted as a typed event: %q", out.String())
	}
}

func TestAsk_ApproveFlagAnswersAndFollowsTheContinuation(t *testing.T) {
	tests := []struct {
		flag, decision, record string
	}{
		{"reject", "a1:reject", "Not approved: Create issue"},
		{"once", "a1:approve_once", "Approved: Create issue"},
		{"session", "a1:approve_session", "Approved for this session: Create issue"},
	}
	for _, tt := range tests {
		t.Run(tt.flag, func(t *testing.T) {
			run := newApprovalServer(t, approvalServerOptions{})
			ios, out, errOut := pipedIOS()
			ios.IsStdoutTTY = true
			if err := runApprovalAsk(t, ios, "--approve="+tt.flag); err != nil {
				t.Fatalf("Execute: %v", err)
			}
			if got := within(t, run.decisions); got != tt.decision {
				t.Errorf("decision = %q, want %q", got, tt.decision)
			}
			// The continuation replays the response, which shows once.
			if out.String() != "Filing. done\n" {
				t.Errorf("stdout = %q, want the answer once", out.String())
			}
			stderr := errOut.String()
			for _, once := range []string{"Approval requested:", tt.record, "Searching documents..."} {
				if strings.Count(stderr, once) != 1 {
					t.Errorf("stderr shows %q other than once: %q", once, stderr)
				}
			}
		})
	}
}

func TestAsk_ContinuationShowsNothingBeforeItsReplayEnd(t *testing.T) {
	newApprovalServer(t, approvalServerOptions{childRequest: true})
	ios, out, errOut := pipedIOS()
	ios.IsStdoutTTY = true
	if err := runApprovalAsk(t, ios, "--approve=once"); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if out.String() != "Filing. done\n" {
		t.Errorf("stdout = %q, want the answer once", out.String())
	}
	// The replay resolves the child's request before the replayed search.
	stderr := errOut.String()
	for _, once := range []string{"Searching documents...", "Approved: Tool c1", "Approved: Create issue"} {
		if strings.Count(stderr, once) != 1 {
			t.Errorf("stderr shows %q other than once: %q", once, stderr)
		}
	}
}

func TestAsk_ContinuationThatFailsAfterItsReplayShowsTheError(t *testing.T) {
	newApprovalServer(t, approvalServerOptions{resumeFails: true})
	ios, out, errOut := pipedIOS()
	err := runApprovalAsk(t, ios, "--approve=once")
	if err == nil || !strings.Contains(err.Error(), "resume failed") {
		t.Fatalf("err = %v, want the continuation's error", err)
	}
	if out.String() != "Filing. \n" {
		t.Errorf("stdout = %q, want only the live text", out.String())
	}
	if strings.Count(errOut.String(), "Approved: Create issue") != 1 {
		t.Errorf("the replayed outcome does not show once: %q", errOut.String())
	}
}

func TestAsk_ContinuationWithoutBufferShowsTheSavedAnswer(t *testing.T) {
	newApprovalServer(t, approvalServerOptions{unbuffered: true})
	ios, out, errOut := pipedIOS()
	if err := runApprovalAsk(t, ios, "--approve=once"); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if out.String() != "Filing. done\n" {
		t.Errorf("stdout = %q, want the rest of the saved answer", out.String())
	}
	if strings.Count(errOut.String(), "Approved: Create issue") != 1 {
		t.Errorf("the saved outcome does not show once: %q", errOut.String())
	}
}

func TestAsk_SavedAnswerAfterAContinuationShowsOnlyItsRest(t *testing.T) {
	newApprovalServer(t, approvalServerOptions{asksAgain: true})
	ios, out, errOut := pipedIOS()
	if err := runApprovalAsk(t, ios, "--approve=once"); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	// The replay's text differs from the live text, and the saved session
	// renders the response as the replay does.
	if out.String() != "Filing. Done filed.\n" {
		t.Errorf("stdout = %q, want each part of the answer once", out.String())
	}
	if strings.Count(errOut.String(), "Approved: Tool a9") != 1 {
		t.Errorf("the saved outcome does not show once: %q", errOut.String())
	}
}

func TestAsk_InterruptedContinuationResumesFromItsCursor(t *testing.T) {
	newApprovalServer(t, approvalServerOptions{interrupted: true})
	ios, out, errOut := pipedIOS()
	if err := runApprovalAsk(t, ios, "--approve=once"); err != nil {
		t.Fatalf("Execute: %v; stderr = %q", err, errOut.String())
	}
	if out.String() != "Filing. done\n" {
		t.Errorf("stdout = %q, want the rest of the answer", out.String())
	}
	if strings.Count(errOut.String(), "Approved: Create issue") != 1 {
		t.Errorf("the outcome does not show once: %q", errOut.String())
	}
}

func TestAsk_PromptEndsWhenAnotherClientDecides(t *testing.T) {
	run := newApprovalServer(t, approvalServerOptions{decidedElsewhere: true})
	ios, _, errOut := interactiveIOS(t)
	done := make(chan error, 1)
	go func() { done <- runApprovalAsk(t, ios) }()

	waitForPrompts(t, errOut, 1)
	within(t, run.sent)
	run.decideElsewhere("a1", "approved")

	if err := within(t, done); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	noDecision(t, run)
	if got := ios.Out.(*syncBuffer).String(); got != "Filing. done\n" {
		t.Errorf("stdout = %q", got)
	}
	if strings.Count(errOut.String(), "Approved: Create issue") != 1 {
		t.Errorf("the other client's decision does not show once: %q", errOut.String())
	}
}

func TestAsk_JSONFollowsTheContinuationWithoutRepeatingEvents(t *testing.T) {
	newApprovalServer(t, approvalServerOptions{})
	ios, out, _ := pipedIOS()
	if err := runApprovalAsk(t, ios, "--json", "--approve=once"); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	var types, text []string
	for _, line := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		var event struct {
			Type  string `json:"type"`
			Event struct {
				Content string `json:"content"`
			} `json:"event"`
		}
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			t.Fatal(err)
		}
		types = append(types, event.Type)
		text = append(text, event.Event.Content)
	}
	want := []string{"session_created", "message_id_info", "message_delta", "search_tool_start", "tool_approval_request", "stop", "tool_approval_resolved", "message_delta", "stop"}
	if strings.Join(types, " ") != strings.Join(want, " ") {
		t.Errorf("event types = %v, want %v", types, want)
	}
	if got := strings.Join(text, ""); got != "Filing. done" {
		t.Errorf("text = %q", got)
	}
}

func TestAsk_InteractivePrompt(t *testing.T) {
	for answer, want := range map[string]string{"y\n": "a1:approve_once", "a\n": "a1:approve_session", "\n": "a1:reject", "": "a1:reject"} {
		t.Run(want+"/"+strings.TrimSpace(answer), func(t *testing.T) {
			run := newApprovalServer(t, approvalServerOptions{})
			ios, out, errOut := pipedIOS()
			ios.In = strings.NewReader(answer)
			ios.IsStderrTTY = true
			if err := runApprovalAsk(t, ios); err != nil {
				t.Fatalf("an answered prompt must not fail the run: %v", err)
			}
			if got := within(t, run.decisions); got != want {
				t.Errorf("decision = %q, want %q", got, want)
			}
			if !strings.Contains(errOut.String(), askPrompt) {
				t.Errorf("no prompt on stderr: %q", errOut.String())
			}
			if out.String() != "Filing. done\n" {
				t.Errorf("answer did not continue: %q", out.String())
			}
		})
	}
}

func TestAsk_PromptsForEachRequestAfterTheStreamStops(t *testing.T) {
	run := newApprovalServer(t, approvalServerOptions{requests: []string{"a1", "a2"}})
	ios, typed, errOut := interactiveIOS(t)
	done := make(chan error, 1)
	go func() { done <- runApprovalAsk(t, ios) }()

	waitForPrompts(t, errOut, 1)
	// The stream has stopped for the decisions; the prompt still waits.
	within(t, run.sent)
	go func() { _, _ = io.WriteString(typed, "y\n") }()
	waitForPrompts(t, errOut, 2)
	go func() { _, _ = io.WriteString(typed, "n\n") }()

	if err := within(t, done); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	for _, want := range []string{"a1:approve_once", "a2:reject"} {
		if got := within(t, run.decisions); got != want {
			t.Fatalf("decision = %q, want %q", got, want)
		}
	}
	if got := ios.Out.(*syncBuffer).String(); got != "Filing. done\n" {
		t.Errorf("stdout = %q", got)
	}
	if !strings.Contains(errOut.String(), "Not approved: Tool a2") {
		t.Errorf("a2's outcome is not reported: %q", errOut.String())
	}
}

func TestAsk_DecisionNoLongerWaitingContinues(t *testing.T) {
	newApprovalServer(t, approvalServerOptions{decisionStatus: http.StatusConflict})
	ios, out, errOut := pipedIOS()
	if err := runApprovalAsk(t, ios, "--approve=once"); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if !strings.Contains(errOut.String(), "No longer waiting: Create issue") || !strings.Contains(out.String(), "done") {
		t.Errorf("stdout=%q stderr=%q", out.String(), errOut.String())
	}
}

func TestAsk_ApprovingADisabledToolRecordsItDisabled(t *testing.T) {
	run := newApprovalServer(t, approvalServerOptions{disabled: true})
	ios, out, errOut := pipedIOS()
	if err := runApprovalAsk(t, ios, "--approve=once"); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if got := within(t, run.decisions); got != "a1:approve_once" {
		t.Errorf("decision = %q", got)
	}
	if !strings.Contains(errOut.String(), "Disabled: Create issue") || !strings.Contains(out.String(), "done") {
		t.Errorf("stdout=%q stderr=%q", out.String(), errOut.String())
	}
}

func TestAsk_InterruptedPromptLeavesTheRequestWaiting(t *testing.T) {
	run := newApprovalServer(t, approvalServerOptions{})
	ios, _, errOut := interactiveIOS(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		cmd := newAskCmd(ios)
		cmd.SetArgs([]string{"file a ticket"})
		done <- cmd.ExecuteContext(ctx)
	}()

	waitForPrompts(t, errOut, 1)
	// The stream stops for the decision before the interrupt.
	within(t, run.sent)
	cancel()

	err := within(t, done)
	if code := exitCode(err); code != exitcodes.ApprovalPending {
		t.Fatalf("exit code = %d (%v), want %d", code, err, exitcodes.ApprovalPending)
	}
	if !strings.Contains(err.Error(), "still waits") {
		t.Errorf("error does not say the request waits: %v", err)
	}
	noStop(t, run)
	noDecision(t, run)
}

func TestAsk_InterruptedPromptShowsNoFurtherRequest(t *testing.T) {
	run := newApprovalServer(t, approvalServerOptions{requests: []string{"a1", "a2"}})
	ios, _, errOut := interactiveIOS(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		cmd := newAskCmd(ios)
		cmd.SetArgs([]string{"file a ticket"})
		done <- cmd.ExecuteContext(ctx)
	}()

	waitForPrompts(t, errOut, 1)
	within(t, run.sent)
	cancel()
	if code := exitCode(within(t, done)); code != exitcodes.ApprovalPending {
		t.Fatalf("exit code = %d, want %d", code, exitcodes.ApprovalPending)
	}
	if stderr := errOut.String(); strings.Count(stderr, askPrompt) != 1 || strings.Contains(stderr, "Tool a2") {
		t.Fatalf("the interrupt showed a further request: %q", stderr)
	}
}

func TestAsk_PromptEndsWhenTheServerEndsTheRequest(t *testing.T) {
	run := newParallelApprovalServer(t, func(send func(string, map[string]any), decisions <-chan string) {
		send("tool_approval_request", requestEvent("a1"))
		// The program that asked ends while its stream keeps running.
		send("tool_approval_resolved", map[string]any{"approval_id": "a1", "outcome": "cancelled"})
		send("message_delta", map[string]any{"content": "done"})
		send("stop", nil)
	})
	ios, _, errOut := interactiveIOS(t)
	if err := runApprovalAsk(t, ios); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if !strings.Contains(errOut.String(), "No longer waiting: Tool a1") || !strings.Contains(ios.Out.(*syncBuffer).String(), "done") {
		t.Errorf("stdout=%q stderr=%q", ios.Out.(*syncBuffer).String(), errOut.String())
	}
	select {
	case got := <-run.decisions:
		t.Errorf("sent decision %q for a request the server ended", got)
	default:
	}
}

// newSavedParkServer answers like a server whose continuations finish
// before ask attaches to them: decisions name no stream and the session is
// idle. After a1's decision the saved response parks at a2; after a2's, it
// has finished.
func newSavedParkServer(t *testing.T) chan string {
	t.Helper()
	decisions := make(chan string, 8)
	var mu sync.Mutex
	decided := 0
	mux := http.NewServeMux()
	mux.HandleFunc("/api/chat/send-chat-message", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "{\"chat_session_id\":%q}\n", testSessionID)
		fmt.Fprintln(w, `{"user_message_id":1,"reserved_assistant_message_id":2}`)
		fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "Filing. "}))
		fmt.Fprintln(w, streamLine("tool_approval_request", requestEvent("a1")))
		fmt.Fprintln(w, streamLine("stop", map[string]any{"stop_reason": "awaiting_user"}))
	})
	mux.HandleFunc("POST /api/chat/approvals/{id}/decision", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		decided++
		mu.Unlock()
		decisions <- r.PathValue("id")
		fmt.Fprintf(w, `{"approval_id":%q,"decision":"APPROVED","decided_via":"USER","continuation":null}`, r.PathValue("id"))
	})
	mux.HandleFunc("/api/chat/chat-session/"+testSessionID+"/status", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `{"is_processing":false}`)
	})
	mux.HandleFunc("/api/chat/get-chat-session/"+testSessionID, func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		resolved := func(id string) string {
			return streamLine("tool_approval_resolved", map[string]any{"approval_id": id, "outcome": "approved"})
		}
		packets := []string{
			streamLine("message_delta", map[string]any{"content": "Filing. "}),
			streamLine("tool_approval_request", requestEvent("a1")),
			resolved("a1"),
			streamLine("message_delta", map[string]any{"content": "Checking. "}),
			streamLine("tool_approval_request", requestEvent("a2")),
		}
		text := "Filing. Checking. "
		if decided >= 2 {
			packets = append(packets, resolved("a2"), streamLine("message_delta", map[string]any{"content": "done"}), streamLine("stop", map[string]any{"stop_reason": "finished"}))
			text += "done"
		} else {
			packets = append(packets, streamLine("stop", map[string]any{"stop_reason": "awaiting_user"}))
		}
		message, _ := json.Marshal(text)
		fmt.Fprintf(w, `{"chat_session_id":%q,"messages":[{"message_id":1,"message":"file a ticket","message_type":"user"},{"message_id":2,"message":%s,"message_type":"assistant"}],"packets":[[%s]]}`,
			testSessionID, message, strings.Join(packets, ","))
	})
	mux.HandleFunc("/api/chat/rename-chat-session", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `{"new_name":"Title"}`)
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	testutil.IsolateConfig(t, srv.URL)
	t.Setenv("CI", "")
	return decisions
}

func TestAsk_SavedResponseThatParksAgainLoadsAfterTheNextDecision(t *testing.T) {
	decisions := newSavedParkServer(t)
	ios, out, errOut := pipedIOS()
	if err := runApprovalAsk(t, ios, "--approve=once"); err != nil {
		t.Fatalf("Execute: %v; stderr = %q", err, errOut.String())
	}
	for _, want := range []string{"a1", "a2"} {
		if got := within(t, decisions); got != want {
			t.Fatalf("decision = %q, want %q", got, want)
		}
	}
	if out.String() != "Filing. Checking. done\n" {
		t.Errorf("stdout = %q, want the finished answer", out.String())
	}
}

func TestAsk_QuietRunThatFailsAfterADecisionPrintsItsOutput(t *testing.T) {
	newApprovalServer(t, approvalServerOptions{unbuffered: true, savedFails: true})
	ios, out, _ := pipedIOS()
	if err := runApprovalAsk(t, ios, "--approve=once", "--quiet"); err == nil {
		t.Fatal("the run did not fail")
	}
	if out.String() != "Filing. \n" {
		t.Errorf("stdout = %q, want the text received before the failure", out.String())
	}
}

func TestAsk_RejectsUnknownApproveValue(t *testing.T) {
	newApprovalServer(t, approvalServerOptions{})
	ios, _, _ := pipedIOS()
	if code := exitCode(runApprovalAsk(t, ios, "--approve=always")); code != exitcodes.BadRequest {
		t.Fatalf("exit code = %d, want %d", code, exitcodes.BadRequest)
	}
}

// syncBuffer is an output buffer that a test reads while ask writes to it.
type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *syncBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

const askPrompt = "[y] approve once / [a] approve for session / [d] show all arguments / [N] reject"

// waitForPrompts waits until stderr shows n prompts.
func waitForPrompts(t *testing.T, errOut *syncBuffer, n int) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for strings.Count(errOut.String(), askPrompt) < n {
		if time.Now().After(deadline) {
			t.Fatalf("stderr does not show %d prompts: %q", n, errOut.String())
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// parallelApprovalRun drives a fake server whose response requests several
// approvals. script writes the stream; decisions records "id:decision".
type parallelApprovalRun struct {
	decisions chan string
}

func newParallelApprovalServer(t *testing.T, script func(send func(event string, obj map[string]any), decisions <-chan string)) *parallelApprovalRun {
	t.Helper()
	run := &parallelApprovalRun{decisions: make(chan string, 8)}
	// The script sees each decision once; the test reads the copy in run.
	scriptDecisions := make(chan string, 8)
	mux := http.NewServeMux()
	mux.HandleFunc("/api/chat/send-chat-message", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "{\"chat_session_id\":%q}\n", testSessionID)
		fmt.Fprintln(w, `{"user_message_id":1,"reserved_assistant_message_id":2}`)
		w.(http.Flusher).Flush()
		script(func(event string, obj map[string]any) {
			fmt.Fprintln(w, streamLine(event, obj))
			w.(http.Flusher).Flush()
		}, scriptDecisions)
	})
	mux.HandleFunc("POST /api/chat/approvals/{id}/decision", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Decision string `json:"decision"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		decision := r.PathValue("id") + ":" + body.Decision
		run.decisions <- decision
		scriptDecisions <- decision
		fmt.Fprintf(w, `{"approval_id":%q,"decision":"APPROVED","decided_via":"USER"}`, r.PathValue("id"))
	})
	mux.HandleFunc("/api/chat/stop-chat-session/"+testSessionID, func(w http.ResponseWriter, r *http.Request) {})
	mux.HandleFunc("/api/chat/chat-session/"+testSessionID+"/status", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `{"is_processing":false}`)
	})
	mux.HandleFunc("/api/chat/rename-chat-session", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `{"new_name":"Title"}`)
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	testutil.IsolateConfig(t, srv.URL)
	t.Setenv("CI", "")
	return run
}

// await waits up to five seconds for ch in a fake server's handler, so a
// regression fails the test instead of blocking the server's shutdown.
func await[T any](ch <-chan T) {
	select {
	case <-ch:
	case <-time.After(5 * time.Second):
	}
}

func requestEvent(id string) map[string]any {
	return map[string]any{"approval_id": id, "tool_call_id": "call-" + id, "tool_name": "tool_" + id, "display_name": "Tool " + id}
}

// interactiveIOS is a terminal whose answers the test types.
func interactiveIOS(t *testing.T) (*iostreams.IOStreams, *io.PipeWriter, *syncBuffer) {
	t.Helper()
	answers, typed := io.Pipe()
	t.Cleanup(func() { _ = typed.Close() })
	errOut := &syncBuffer{}
	return &iostreams.IOStreams{In: answers, Out: &syncBuffer{}, ErrOut: errOut, IsStdinTTY: true, IsStderrTTY: true}, typed, errOut
}

func TestAsk_LateAnswerDoesNotDecideTheNextRequest(t *testing.T) {
	aShown := make(chan struct{})
	run := newParallelApprovalServer(t, func(send func(string, map[string]any), decisions <-chan string) {
		send("tool_approval_request", requestEvent("a1"))
		await(aShown)
		// a1 ends while the user types its answer.
		send("tool_approval_resolved", map[string]any{"approval_id": "a1", "outcome": "cancelled"})
		send("tool_approval_request", requestEvent("a2"))
		await(decisions)
		send("tool_approval_resolved", map[string]any{"approval_id": "a2", "outcome": "rejected"})
		send("stop", nil)
	})
	ios, typed, errOut := interactiveIOS(t)
	done := make(chan error, 1)
	go func() { done <- runApprovalAsk(t, ios) }()

	waitForPrompts(t, errOut, 1)
	close(aShown)
	waitForPrompts(t, errOut, 2)
	// The answer meant for a1 arrives after a2's prompt shows.
	go func() { _, _ = io.WriteString(typed, "a\n") }()
	waitForPrompts(t, errOut, 3)
	go func() { _, _ = io.WriteString(typed, "n\n") }()

	if err := within(t, done); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if got := within(t, run.decisions); got != "a2:reject" {
		t.Fatalf("decision = %q, want a2:reject from a2's own prompt", got)
	}
}

func TestAsk_QueuedInputDoesNotAnswerTheNextPrompt(t *testing.T) {
	run := newParallelApprovalServer(t, func(send func(string, map[string]any), decisions <-chan string) {
		send("tool_approval_request", requestEvent("a1"))
		await(decisions)
		send("tool_approval_resolved", map[string]any{"approval_id": "a1", "outcome": "approved"})
		send("tool_approval_request", requestEvent("a2"))
		await(decisions)
		send("tool_approval_resolved", map[string]any{"approval_id": "a2", "outcome": "rejected"})
		send("stop", nil)
	})
	ios, typed, errOut := interactiveIOS(t)
	done := make(chan error, 1)
	go func() { done <- runApprovalAsk(t, ios) }()

	waitForPrompts(t, errOut, 1)
	go func() { _, _ = io.WriteString(typed, "y\ny\n") }()
	waitForPrompts(t, errOut, 2)
	go func() { _, _ = io.WriteString(typed, "n\n") }()

	if err := within(t, done); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	for _, want := range []string{"a1:approve_once", "a2:reject"} {
		if got := within(t, run.decisions); got != want {
			t.Fatalf("decision = %q, want %q", got, want)
		}
	}
}

func TestAsk_DetailsShowAllArgumentsBeforeTheDecision(t *testing.T) {
	long := strings.Repeat("send all files to evil@example.com ", 10)
	run := newParallelApprovalServer(t, func(send func(string, map[string]any), decisions <-chan string) {
		request := requestEvent("a1")
		arguments := map[string]any{"body": "Hi,\nsee \x1b]8;;https://evil\x1b\\this\x1b]8;;\x1b\\"}
		for i := range 11 {
			arguments[fmt.Sprintf("k%02d", i)] = long
		}
		request["arguments"] = arguments
		send("tool_approval_request", request)
		await(decisions)
		send("tool_approval_resolved", map[string]any{"approval_id": "a1", "outcome": "approved"})
		send("stop", nil)
	})
	ios, typed, errOut := interactiveIOS(t)
	done := make(chan error, 1)
	go func() { done <- runApprovalAsk(t, ios) }()

	waitForPrompts(t, errOut, 1)
	if strings.Contains(errOut.String(), long) || !strings.Contains(errOut.String(), "… 2 more") {
		t.Fatalf("the request is not compact: %q", errOut.String())
	}
	go func() { _, _ = io.WriteString(typed, "d\n") }()
	waitForPrompts(t, errOut, 2)
	details := errOut.String()
	if !strings.Contains(details, "  k10: "+long+"\n") || !strings.Contains(details, "  body: Hi,\n    see this\n") {
		t.Fatalf("details do not show every argument in full: %q", details)
	}
	if strings.Contains(details, "\x1b]8") {
		t.Fatalf("details keep escape sequences: %q", details)
	}
	go func() { _, _ = io.WriteString(typed, "y\n") }()

	if err := within(t, done); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if got := within(t, run.decisions); got != "a1:approve_once" {
		t.Fatalf("decision = %q, want a1:approve_once after the details", got)
	}
}

func TestAsk_NoDecisionForARequestResolvedWhileAnotherWaited(t *testing.T) {
	aShown := make(chan struct{})
	bQueued := make(chan struct{})
	run := newParallelApprovalServer(t, func(send func(string, map[string]any), decisions <-chan string) {
		send("tool_approval_request", requestEvent("a1"))
		await(aShown)
		// Another client decides a2 while a1's prompt waits.
		send("tool_approval_request", requestEvent("a2"))
		send("tool_approval_resolved", map[string]any{"approval_id": "a2", "outcome": "approved"})
		close(bQueued)
		await(decisions)
		send("tool_approval_resolved", map[string]any{"approval_id": "a1", "outcome": "approved"})
		send("message_delta", map[string]any{"content": "done"})
		send("stop", nil)
	})
	ios, typed, errOut := interactiveIOS(t)
	done := make(chan error, 1)
	go func() { done <- runApprovalAsk(t, ios) }()

	waitForPrompts(t, errOut, 1)
	close(aShown)
	within(t, bQueued)
	// a1's answer can arrive before or after a2's events; a prompt that a2
	// shows ends with its resolution, since no further input arrives.
	_, _ = io.WriteString(typed, "y\n")

	if err := within(t, done); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if got := within(t, run.decisions); got != "a1:approve_once" {
		t.Fatalf("decision = %q", got)
	}
	select {
	case got := <-run.decisions:
		t.Fatalf("sent %q for a request another client resolved", got)
	default:
	}
	stderr := errOut.String()
	if !strings.Contains(stderr, "Approved: Tool a2") {
		t.Fatalf("a2's outcome is not reported: %q", stderr)
	}
}

func TestAsk_DecisionFailureStopsTheResponseBeforeExit(t *testing.T) {
	for _, args := range [][]string{{"--approve=once"}, {"--approve=once", "--json"}} {
		// A running stream's owner stops it; a waiting response cannot be
		// stopped and keeps its request.
		for _, waiting := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/waiting=%t", strings.Join(args, " "), waiting), func(t *testing.T) {
				stopped := make(chan string, 1)
				mux := http.NewServeMux()
				mux.HandleFunc("/api/chat/send-chat-message", func(w http.ResponseWriter, r *http.Request) {
					fmt.Fprintf(w, "{\"chat_session_id\":%q}\n", testSessionID)
					fmt.Fprintln(w, `{"user_message_id":1,"reserved_assistant_message_id":2}`)
					fmt.Fprintln(w, streamLine("tool_approval_request", requestEvent("a1")))
					if waiting {
						fmt.Fprintln(w, streamLine("stop", map[string]any{"stop_reason": "awaiting_user"}))
						return
					}
					w.(http.Flusher).Flush()
					<-r.Context().Done()
				})
				mux.HandleFunc("/api/chat/approvals/a1/decision", func(w http.ResponseWriter, r *http.Request) {
					http.Error(w, `{"detail":"boom"}`, http.StatusInternalServerError)
				})
				mux.HandleFunc("/api/chat/stop-chat-session/"+testSessionID, func(w http.ResponseWriter, r *http.Request) {
					stopped <- r.URL.Query().Get("stream_id")
				})
				srv := httptest.NewServer(mux)
				t.Cleanup(srv.Close)
				testutil.IsolateConfig(t, srv.URL)
				t.Setenv("CI", "")
				ios, _, _ := pipedIOS()

				if err := runApprovalAsk(t, ios, args...); exitCode(err) == exitcodes.Success {
					t.Fatal("a failed decision must fail the run")
				}
				select {
				case id := <-stopped:
					if waiting || id != "2" {
						t.Fatalf("Stop stream_id = %q; want 2 only for a running stream", id)
					}
				default:
					if !waiting {
						t.Fatal("ask returned before the running response was stopped")
					}
				}
			})
		}
	}
}
