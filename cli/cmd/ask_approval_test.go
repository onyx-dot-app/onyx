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
}

// approvalServerOptions changes how the fake server answers.
type approvalServerOptions struct {
	// The decision endpoint's status.
	decisionStatus int
	// The tool is disabled by a policy, so an approval rejects it.
	disabled bool
	// The approval ids of the response's requests; "a1" when empty.
	requests []string
}

// newApprovalServer streams some text and the response's tool approval
// requests, then stops for the decisions. Once every request is decided, the
// response continues on stream 3, which replays the response from its start
// and finishes the answer.
func newApprovalServer(t *testing.T, opts approvalServerOptions) *approvalRun {
	t.Helper()
	if opts.decisionStatus == 0 {
		opts.decisionStatus = http.StatusOK
	}
	if len(opts.requests) == 0 {
		opts.requests = []string{"a1"}
	}
	run := &approvalRun{decisions: make(chan string, 8), stops: make(chan string, 8)}
	requests := make([]map[string]any, len(opts.requests))
	for i, id := range opts.requests {
		requests[i] = requestEvent(id)
	}
	requests[0]["display_name"] = "Create issue"
	requests[0]["arguments"] = map[string]any{"title": "Bug\x1b]52;c;ZWNobyBoaQ==\x07 report"}
	var mu sync.Mutex
	// The outcome of each decided request, by approval id.
	outcomes := map[string]string{}
	continuing := false
	mux := http.NewServeMux()
	mux.HandleFunc("/api/chat/send-chat-message", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "{\"chat_session_id\":%q}\n", testSessionID)
		fmt.Fprintln(w, `{"user_message_id":1,"reserved_assistant_message_id":2}`)
		fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "Filing. "}))
		for _, request := range requests {
			fmt.Fprintln(w, streamLine("tool_approval_request", request))
		}
		fmt.Fprintln(w, streamLine("stop", map[string]any{"stop_reason": "awaiting_approval"}))
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
		continuing = len(outcomes) == len(requests)
		mu.Unlock()
		if opts.decisionStatus != http.StatusOK {
			w.WriteHeader(opts.decisionStatus)
			fmt.Fprint(w, `{"error_code":"CONFLICT","detail":"This request was already decided or is no longer waiting"}`)
			return
		}
		fmt.Fprintf(w, `{"approval_id":%q,"decision":%q,"decided_via":%q}`, id, decision, decidedVia)
	})
	mux.HandleFunc("/api/chat/chat-session/"+testSessionID+"/status", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if continuing {
			fmt.Fprint(w, `{"is_processing":true,"current_stream":{"stream_id":3}}`)
			return
		}
		fmt.Fprint(w, `{"is_processing":false}`)
	})
	mux.HandleFunc("/api/chat/chat-session/"+testSessionID+"/resume-stream", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if !continuing || r.URL.Query().Get("stream_id") != "3" || r.URL.Query().Get("cursor") != "0" {
			http.NotFound(w, r)
			return
		}
		fmt.Fprintln(w, `{"stream_id":3,"next_cursor":0,"replay_complete":false}`)
		fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "Filing. "}))
		for _, request := range requests {
			fmt.Fprintln(w, streamLine("tool_approval_request", request))
		}
		for _, request := range requests {
			id := request["approval_id"]
			fmt.Fprintln(w, streamLine("tool_approval_resolved", map[string]any{"approval_id": id, "outcome": outcomes[id.(string)]}))
		}
		fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "done"}))
		fmt.Fprintln(w, streamLine("stop", nil))
		fmt.Fprintf(w, "{\"stream_id\":3,\"next_cursor\":%d,\"replay_complete\":true}\n", 4+2*len(requests))
		continuing = false
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
		if got := <-run.decisions; got != want {
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
	if got := <-run.decisions; got != "a1:reject" {
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
			if err := runApprovalAsk(t, ios, "--approve="+tt.flag); err != nil {
				t.Fatalf("Execute: %v", err)
			}
			if got := <-run.decisions; got != tt.decision {
				t.Errorf("decision = %q, want %q", got, tt.decision)
			}
			// The continuation replays "Filing. ", which shows once.
			if out.String() != "Filing. done\n" {
				t.Errorf("stdout = %q, want the answer once", out.String())
			}
			stderr := errOut.String()
			if strings.Count(stderr, "Approval requested:") != 1 || strings.Count(stderr, tt.record) != 1 {
				t.Errorf("stderr shows the request or its outcome other than once: %q", stderr)
			}
		})
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
	want := []string{"session_created", "message_id_info", "message_delta", "tool_approval_request", "stop", "tool_approval_resolved", "message_delta", "stop"}
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
			if got := <-run.decisions; got != want {
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
	time.Sleep(100 * time.Millisecond)
	go func() { _, _ = io.WriteString(typed, "y\n") }()
	waitForPrompts(t, errOut, 2)
	go func() { _, _ = io.WriteString(typed, "n\n") }()

	if err := <-done; err != nil {
		t.Fatalf("Execute: %v", err)
	}
	for _, want := range []string{"a1:approve_once", "a2:reject"} {
		if got := <-run.decisions; got != want {
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
	if got := <-run.decisions; got != "a1:approve_once" {
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
	// Let the stream stop for the decision before the interrupt.
	time.Sleep(100 * time.Millisecond)
	cancel()

	err := <-done
	if code := exitCode(err); code != exitcodes.ApprovalPending {
		t.Fatalf("exit code = %d (%v), want %d", code, err, exitcodes.ApprovalPending)
	}
	if !strings.Contains(err.Error(), "still waits") {
		t.Errorf("error does not say the request waits: %v", err)
	}
	noStop(t, run)
	noDecision(t, run)
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
		<-aShown
		// a1 ends while the user types its answer.
		send("tool_approval_resolved", map[string]any{"approval_id": "a1", "outcome": "cancelled"})
		send("tool_approval_request", requestEvent("a2"))
		<-decisions
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

	if err := <-done; err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if got := <-run.decisions; got != "a2:reject" {
		t.Fatalf("decision = %q, want a2:reject from a2's own prompt", got)
	}
}

func TestAsk_QueuedInputDoesNotAnswerTheNextPrompt(t *testing.T) {
	run := newParallelApprovalServer(t, func(send func(string, map[string]any), decisions <-chan string) {
		send("tool_approval_request", requestEvent("a1"))
		<-decisions
		send("tool_approval_resolved", map[string]any{"approval_id": "a1", "outcome": "approved"})
		send("tool_approval_request", requestEvent("a2"))
		<-decisions
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

	if err := <-done; err != nil {
		t.Fatalf("Execute: %v", err)
	}
	for _, want := range []string{"a1:approve_once", "a2:reject"} {
		if got := <-run.decisions; got != want {
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
		<-decisions
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

	if err := <-done; err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if got := <-run.decisions; got != "a1:approve_once" {
		t.Fatalf("decision = %q, want a1:approve_once after the details", got)
	}
}

func TestAsk_NoPromptForARequestResolvedWhileAnotherWaited(t *testing.T) {
	aShown := make(chan struct{})
	bQueued := make(chan struct{})
	run := newParallelApprovalServer(t, func(send func(string, map[string]any), decisions <-chan string) {
		send("tool_approval_request", requestEvent("a1"))
		<-aShown
		// Another client decides a2 while a1's prompt waits.
		send("tool_approval_request", requestEvent("a2"))
		send("tool_approval_resolved", map[string]any{"approval_id": "a2", "outcome": "approved"})
		close(bQueued)
		<-decisions
		send("tool_approval_resolved", map[string]any{"approval_id": "a1", "outcome": "approved"})
		send("message_delta", map[string]any{"content": "done"})
		send("stop", nil)
	})
	ios, typed, errOut := interactiveIOS(t)
	done := make(chan error, 1)
	go func() { done <- runApprovalAsk(t, ios) }()

	waitForPrompts(t, errOut, 1)
	close(aShown)
	<-bQueued
	// Let ask take a2's events off the stream before a1's answer arrives.
	time.Sleep(200 * time.Millisecond)
	_, _ = io.WriteString(typed, "y\n")
	_ = typed.Close()

	if err := <-done; err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if got := <-run.decisions; got != "a1:approve_once" {
		t.Fatalf("decision = %q", got)
	}
	select {
	case got := <-run.decisions:
		t.Fatalf("sent %q for a request another client resolved", got)
	default:
	}
	stderr := errOut.String()
	if n := strings.Count(stderr, askPrompt); n != 1 {
		t.Fatalf("prompts = %d, want 1: %q", n, stderr)
	}
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
						fmt.Fprintln(w, streamLine("stop", map[string]any{"stop_reason": "awaiting_approval"}))
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
