package cmd

import (
	"bytes"
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
	decisions chan string
}

// approvalServerOptions changes how the fake server answers.
type approvalServerOptions struct {
	// The decision endpoint's status.
	decisionStatus int
	// The tool is disabled by a policy, so an approval rejects it.
	disabled bool
	// The server ends the request without a decision, as at its deadline.
	expire bool
}

// newApprovalServer streams one tool approval request, waits for the decision,
// then finishes the answer.
func newApprovalServer(t *testing.T, opts approvalServerOptions) *approvalRun {
	t.Helper()
	if opts.decisionStatus == 0 {
		opts.decisionStatus = http.StatusOK
	}
	run := &approvalRun{decisions: make(chan string, 1)}
	decided := make(chan string, 1)
	if opts.expire {
		decided <- "expired"
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/api/chat/send-chat-message", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "{\"chat_session_id\":%q}\n", testSessionID)
		fmt.Fprintln(w, `{"user_message_id":1,"reserved_assistant_message_id":2}`)
		fmt.Fprintln(w, streamLine("tool_approval_request", map[string]any{
			"approval_id":  "a1",
			"tool_call_id": "call-1",
			"tool_name":    "mcp__3__linear__create_issue",
			"display_name": "Create issue",
			"arguments":    map[string]any{"title": "Bug\x1b]52;c;ZWNobyBoaQ==\x07 report"},
			"expires_at":   "2099-01-01T00:00:00Z",
		}))
		w.(http.Flusher).Flush()
		select {
		case outcome := <-decided:
			fmt.Fprintln(w, streamLine("tool_approval_resolved", map[string]any{"approval_id": "a1", "outcome": outcome}))
			fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "done"}))
			fmt.Fprintln(w, streamLine("stop", nil))
		case <-r.Context().Done():
		}
	})
	mux.HandleFunc("/api/chat/approvals/a1/decision", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Decision string `json:"decision"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		run.decisions <- body.Decision
		if opts.decisionStatus != http.StatusOK {
			w.WriteHeader(opts.decisionStatus)
			fmt.Fprint(w, `{"error_code":"CONFLICT","detail":"This request was already decided or is no longer waiting"}`)
			decided <- "approved"
			return
		}
		outcome, decision, decidedVia := "approved", "APPROVED", "USER"
		switch {
		case body.Decision == "reject":
			outcome, decision = "rejected", "REJECTED"
		case opts.disabled:
			outcome, decision, decidedVia = "disabled", "REJECTED", "POLICY"
		case body.Decision == "approve_session":
			outcome, decidedVia = "approved_for_chat", "SESSION_GRANT"
		}
		decided <- outcome
		fmt.Fprintf(w, `{"approval_id":"a1","decision":%q,"decided_via":%q}`, decision, decidedVia)
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

func TestAsk_NonInteractiveRejectsAndExitsWithApprovalRequired(t *testing.T) {
	run := newApprovalServer(t, approvalServerOptions{})
	ios, _, errOut := pipedIOS()
	err := runApprovalAsk(t, ios)
	if code := exitCode(err); code != exitcodes.ApprovalRequired {
		t.Fatalf("exit code = %d (%v), want %d", code, err, exitcodes.ApprovalRequired)
	}
	if !strings.Contains(err.Error(), "--approve=") {
		t.Errorf("error does not explain how to proceed: %v", err)
	}
	if got := <-run.decisions; got != "reject" {
		t.Errorf("decision = %q, want reject so the server stops waiting", got)
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
	if got := <-run.decisions; got != "reject" {
		t.Errorf("decision = %q", got)
	}
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

func TestAsk_ApproveFlagAnswersAndContinues(t *testing.T) {
	tests := []struct {
		flag, decision, record string
	}{
		{"reject", "reject", "Not approved: Create issue"},
		{"once", "approve_once", "Approved: Create issue"},
		{"session", "approve_session", "Approved for this session: Create issue"},
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
			if !strings.Contains(out.String(), "done") {
				t.Errorf("answer did not continue after the decision: %q", out.String())
			}
			if !strings.Contains(errOut.String(), tt.record) {
				t.Errorf("stderr lacks %q: %q", tt.record, errOut.String())
			}
		})
	}
}

func TestAsk_InteractivePrompt(t *testing.T) {
	for answer, want := range map[string]string{"y\n": "approve_once", "a\n": "approve_session", "\n": "reject", "": "reject"} {
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
			if !strings.Contains(errOut.String(), "[y] approve once / [a] approve for session / [N] reject") {
				t.Errorf("no prompt on stderr: %q", errOut.String())
			}
			if !strings.Contains(out.String(), "done") {
				t.Errorf("answer did not continue: %q", out.String())
			}
		})
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
	if got := <-run.decisions; got != "approve_once" {
		t.Errorf("decision = %q", got)
	}
	if !strings.Contains(errOut.String(), "Disabled: Create issue") || !strings.Contains(out.String(), "done") {
		t.Errorf("stdout=%q stderr=%q", out.String(), errOut.String())
	}
}

func TestAsk_PromptEndsWhenTheServerEndsTheRequest(t *testing.T) {
	run := newApprovalServer(t, approvalServerOptions{expire: true})
	ios, out, errOut := pipedIOS()
	// Nobody answers the prompt.
	answer, unanswered := io.Pipe()
	t.Cleanup(func() { _ = unanswered.Close() })
	ios.In = answer
	ios.IsStderrTTY = true
	if err := runApprovalAsk(t, ios); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if !strings.Contains(errOut.String(), "Timed out: Create issue") || !strings.Contains(out.String(), "done") {
		t.Errorf("stdout=%q stderr=%q", out.String(), errOut.String())
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

const askPrompt = "[y] approve once / [a] approve for session / [N] reject"

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
		// a1 times out while the user types its answer.
		send("tool_approval_resolved", map[string]any{"approval_id": "a1", "outcome": "expired"})
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
