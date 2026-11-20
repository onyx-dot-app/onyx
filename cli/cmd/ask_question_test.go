package cmd

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/question"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

// questionEvent asks two questions as q1.
func questionEvent() map[string]any {
	return map[string]any{
		"question_request_id": "q1",
		"tool_call_id":        "call-q1",
		"questions": []any{
			map[string]any{"id": "scope", "header": "Scope", "question": "Which teams?", "options": []any{
				map[string]any{"label": "Company", "description": "All teams."},
				map[string]any{"label": "Team", "description": "Only yours."},
			}},
			map[string]any{"id": "region", "header": "Reg\x1b]52;c;ZWNobyBoaQ==\x07ion", "question": "Which region?", "options": []any{
				map[string]any{"label": "EU", "description": "Europe."},
				map[string]any{"label": "US", "description": "America."},
			}},
		},
	}
}

// questionServerOptions changes how the fake question server answers.
type questionServerOptions struct {
	// The answers name no stream; the saved session shows the finished
	// answer.
	saved bool
	// The answers route's status.
	answerStatus int
}

// questionRun is what the fake question server saw during one ask run.
type questionRun struct {
	// bodies receives the body of each answers request.
	bodies chan []byte
	// sent closes when the server finished the stream of the message.
	sent chan struct{}
	// answerElsewhere answers q1 as another client does; the status then
	// names the continuation and a new approvals version.
	answerElsewhere func()
}

// newQuestionServer streams some text and q1, then stops for the answers.
// The answers name stream 3 as the continuation, which replays the response
// and finishes the answer.
func newQuestionServer(t *testing.T, opts questionServerOptions) *questionRun {
	t.Helper()
	if opts.answerStatus == 0 {
		opts.answerStatus = http.StatusOK
	}
	run := &questionRun{bodies: make(chan []byte, 4), sent: make(chan struct{})}
	var mu sync.Mutex
	var answers any
	// continuing marks stream 3 as the running continuation, and elsewhere
	// an answer that another client sent.
	answered, continuing, elsewhere := false, false, false
	run.answerElsewhere = func() {
		mu.Lock()
		defer mu.Unlock()
		answers = []any{map[string]any{"question_id": "scope", "option_label": "Team"}, map[string]any{"question_id": "region", "option_label": "EU"}}
		answered, continuing, elsewhere = true, true, true
	}
	resolved := func() string {
		return streamLine("tool_question_resolved", map[string]any{"question_request_id": "q1", "outcome": "answered", "answered_via": "card", "answers": answers})
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/api/chat/send-chat-message", func(w http.ResponseWriter, r *http.Request) {
		defer close(run.sent)
		fmt.Fprintf(w, "{\"chat_session_id\":%q}\n", testSessionID)
		fmt.Fprintln(w, `{"user_message_id":1,"reserved_assistant_message_id":2}`)
		fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "Drafting. "}))
		fmt.Fprintln(w, streamLine("tool_question_request", questionEvent()))
		fmt.Fprintln(w, streamLine("stop", map[string]any{"stop_reason": "awaiting_user"}))
	})
	mux.HandleFunc("POST /api/chat/question-requests/{id}/answers", func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		run.bodies <- body
		if opts.answerStatus != http.StatusOK {
			w.WriteHeader(opts.answerStatus)
			fmt.Fprint(w, `{"error_code":"CONFLICT","detail":"This question was already answered or is no longer waiting"}`)
			return
		}
		var parsed struct {
			Answers any `json:"answers"`
		}
		_ = json.Unmarshal(body, &parsed)
		mu.Lock()
		answers, answered, continuing = parsed.Answers, true, !opts.saved
		mu.Unlock()
		continuation := `{"stream_id":3,"response_ids":[2]}`
		if opts.saved {
			continuation = "null"
		}
		fmt.Fprintf(w, `{"question_request_id":%q,"continuation":%s}`, r.PathValue("id"), continuation)
	})
	mux.HandleFunc("/api/chat/chat-session/"+testSessionID+"/status", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if continuing && elsewhere {
			fmt.Fprint(w, `{"is_processing":true,"current_stream":{"stream_id":3,"response_ids":[2]},"approvals_version":"v2"}`)
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
		fmt.Fprintln(w, `{"user_message_id":1,"reserved_assistant_message_id":2}`)
		fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "Drafting."}))
		fmt.Fprintln(w, streamLine("tool_question_request", questionEvent()))
		fmt.Fprintln(w, resolved())
		fmt.Fprintln(w, streamLine("replay_end", nil))
		fmt.Fprintln(w, resolved())
		fmt.Fprintln(w, streamLine("message_delta", map[string]any{"content": "done"}))
		fmt.Fprintln(w, streamLine("stop", nil))
		fmt.Fprintln(w, `{"stream_id":3,"next_cursor":9,"replay_complete":true}`)
		continuing = false
	})
	mux.HandleFunc("/api/chat/get-chat-session/"+testSessionID, func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		packets := []string{
			streamLine("message_delta", map[string]any{"content": "Drafting. "}),
			streamLine("tool_question_request", questionEvent()),
		}
		text := "Drafting. "
		version := "v1"
		if answered || opts.answerStatus != http.StatusOK {
			packets = append(packets, resolved(), streamLine("message_delta", map[string]any{"content": "done"}), streamLine("stop", map[string]any{"stop_reason": "finished"}))
			text += "done"
			version = "v2"
		} else {
			packets = append(packets, streamLine("stop", map[string]any{"stop_reason": "awaiting_user"}))
		}
		fmt.Fprintf(w, `{"chat_session_id":%q,"approvals_version":%q,"messages":[{"message_id":1,"message":"draft the report","message_type":"user"},{"message_id":2,"message":%q,"message_type":"assistant"}],"packets":[[%s]]}`,
			testSessionID, version, text, strings.Join(packets, ","))
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

// sentAnswers decodes the answers of a request body.
func sentAnswers(t *testing.T, body []byte) []map[string]any {
	t.Helper()
	var parsed struct {
		Answers []map[string]any `json:"answers"`
		Message *string          `json:"message"`
	}
	if err := json.Unmarshal(body, &parsed); err != nil {
		t.Fatal(err)
	}
	if parsed.Message != nil {
		t.Fatalf("ask sent a message: %s", body)
	}
	return parsed.Answers
}

var noAnswers = []map[string]any{
	{"question_id": "scope", "user_note": question.NoAnswer},
	{"question_id": "region", "user_note": question.NoAnswer},
}

func TestAsk_NonInteractiveQuestionHasNoAnswerFinishesAndExitsWithQuestionUnanswered(t *testing.T) {
	run := newQuestionServer(t, questionServerOptions{})
	ios, out, errOut := pipedIOS()
	err := runApprovalAsk(t, ios)
	if code := exitCode(err); code != exitcodes.QuestionUnanswered {
		t.Fatalf("exit code = %d (%v), want %d", code, err, exitcodes.QuestionUnanswered)
	}
	if !strings.Contains(err.Error(), "--questions=skip") {
		t.Errorf("error does not explain how to proceed: %v", err)
	}
	if got := sentAnswers(t, within(t, run.bodies)); !reflect.DeepEqual(got, noAnswers) {
		t.Errorf("answers = %v, want %v", got, noAnswers)
	}
	if out.String() != "Drafting. done\n" {
		t.Errorf("stdout = %q, want the finished answer", out.String())
	}
	stderr := errOut.String()
	for _, want := range []string{"Question: Scope", "Which teams?", "1. Company: All teams.", "2. Team: Only yours.", "Question: Region"} {
		if !strings.Contains(stderr, want) {
			t.Errorf("stderr lacks %q: %q", want, stderr)
		}
	}
	if strings.ContainsAny(stderr, "\x1b\x07") {
		t.Errorf("stderr keeps control characters from the model's questions: %q", stderr)
	}
}

func TestAsk_QuestionsSkipFinishesWithoutFailing(t *testing.T) {
	run := newQuestionServer(t, questionServerOptions{})
	ios, out, _ := pipedIOS()
	if err := runApprovalAsk(t, ios, "--questions=skip"); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if got := sentAnswers(t, within(t, run.bodies)); !reflect.DeepEqual(got, noAnswers) {
		t.Errorf("answers = %v", got)
	}
	if out.String() != "Drafting. done\n" {
		t.Errorf("stdout = %q", out.String())
	}
}

func TestAsk_JSONEmitsTheQuestionsAndNeverPrompts(t *testing.T) {
	run := newQuestionServer(t, questionServerOptions{})
	ios, out, _ := pipedIOS()
	ios.IsStderrTTY = true // a terminal does not make --json interactive
	err := runApprovalAsk(t, ios, "--json")
	if code := exitCode(err); code != exitcodes.QuestionUnanswered {
		t.Fatalf("exit code = %d (%v), want %d", code, err, exitcodes.QuestionUnanswered)
	}
	within(t, run.bodies)
	requests, resolutions := 0, 0
	for _, line := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		var event struct {
			Type  string `json:"type"`
			Event struct {
				QuestionRequestID string           `json:"question_request_id"`
				Questions         []map[string]any `json:"questions"`
			} `json:"event"`
		}
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			t.Fatal(err)
		}
		switch event.Type {
		case "tool_question_request":
			requests++
			if event.Event.QuestionRequestID != "q1" || len(event.Event.Questions) != 2 {
				t.Errorf("question request = %s", line)
			}
		case "tool_question_resolved":
			resolutions++
		}
	}
	if requests != 1 || resolutions != 1 {
		t.Fatalf("stdout shows %d requests and %d resolutions: %q", requests, resolutions, out.String())
	}
}

const questionPromptText = "choose an option / type your own answer / [Enter] no answer"

func TestAsk_PromptsForEachQuestion(t *testing.T) {
	run := newQuestionServer(t, questionServerOptions{})
	ios, typed, errOut := interactiveIOS(t)
	done := make(chan error, 1)
	go func() { done <- runApprovalAsk(t, ios) }()

	waitForText(t, errOut, questionPromptText, 1)
	go func() { _, _ = io.WriteString(typed, "2\n") }()
	waitForText(t, errOut, questionPromptText, 2)
	go func() { _, _ = io.WriteString(typed, "EU only\n") }()

	if err := within(t, done); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	want := []map[string]any{
		{"question_id": "scope", "option_label": "Team"},
		{"question_id": "region", "user_note": "EU only"},
	}
	if got := sentAnswers(t, within(t, run.bodies)); !reflect.DeepEqual(got, want) {
		t.Errorf("answers = %v, want %v", got, want)
	}
	if got := ios.Out.(*syncBuffer).String(); got != "Drafting. done\n" {
		t.Errorf("stdout = %q", got)
	}
	if !strings.Contains(errOut.String(), "Answered: Scope: Team; Region: EU only") {
		t.Errorf("the answers are not reported: %q", errOut.String())
	}
}

func TestAsk_AnswerWithoutContinuationShowsTheSavedAnswer(t *testing.T) {
	newQuestionServer(t, questionServerOptions{saved: true})
	ios, out, errOut := pipedIOS()
	if err := runApprovalAsk(t, ios, "--questions=skip"); err != nil {
		t.Fatalf("Execute: %v; stderr = %q", err, errOut.String())
	}
	if out.String() != "Drafting. done\n" {
		t.Errorf("stdout = %q, want the finished answer", out.String())
	}
}

func TestAsk_RejectsUnknownQuestionsValue(t *testing.T) {
	newQuestionServer(t, questionServerOptions{})
	ios, _, _ := pipedIOS()
	if code := exitCode(runApprovalAsk(t, ios, "--questions=always")); code != exitcodes.BadRequest {
		t.Fatalf("exit code = %d, want %d", code, exitcodes.BadRequest)
	}
}

func TestAsk_QuestionAnsweredElsewhereFirstDoesNotFail(t *testing.T) {
	run := newQuestionServer(t, questionServerOptions{answerStatus: http.StatusConflict})
	ios, out, errOut := pipedIOS()
	if err := runApprovalAsk(t, ios); err != nil {
		t.Fatalf("an answer that another client gave first must not fail the run: %v", err)
	}
	within(t, run.bodies)
	if out.String() != "Drafting. done\n" {
		t.Errorf("stdout = %q, want the finished answer", out.String())
	}
	if !strings.Contains(errOut.String(), "No longer waiting: Scope, Region") {
		t.Errorf("stderr = %q", errOut.String())
	}
}

func TestAsk_InterruptedQuestionPromptLeavesTheQuestionWaiting(t *testing.T) {
	run := newQuestionServer(t, questionServerOptions{})
	ios, _, errOut := interactiveIOS(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		cmd := newAskCmd(ios)
		cmd.SetArgs([]string{"draft the report"})
		done <- cmd.ExecuteContext(ctx)
	}()

	waitForText(t, errOut, questionPromptText, 1)
	within(t, run.sent)
	cancel()

	err := within(t, done)
	if code := exitCode(err); code != exitcodes.ApprovalPending {
		t.Fatalf("exit code = %d (%v), want %d", code, err, exitcodes.ApprovalPending)
	}
	select {
	case body := <-run.bodies:
		t.Errorf("sent answers %s", body)
	default:
	}
}

func TestAsk_QuestionPromptEndsWhenAnotherClientAnswers(t *testing.T) {
	run := newQuestionServer(t, questionServerOptions{})
	ios, _, errOut := interactiveIOS(t)
	done := make(chan error, 1)
	go func() { done <- runApprovalAsk(t, ios) }()

	waitForText(t, errOut, questionPromptText, 1)
	// The stream has stopped; only the saved session shows the answer.
	within(t, run.sent)
	run.answerElsewhere()

	if err := within(t, done); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	select {
	case body := <-run.bodies:
		t.Errorf("sent answers %s", body)
	default:
	}
	if got := ios.Out.(*syncBuffer).String(); got != "Drafting. done\n" {
		t.Errorf("stdout = %q", got)
	}
	if strings.Count(errOut.String(), "Answered: Scope: Team; Region: EU") != 1 {
		t.Errorf("the other client's answer does not show once: %q", errOut.String())
	}
	if strings.Count(errOut.String(), questionPromptText) != 1 {
		t.Errorf("ask prompted again after the answer: %q", errOut.String())
	}
}
