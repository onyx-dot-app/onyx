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
	"testing"

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
