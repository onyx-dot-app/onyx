package tui

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/charmbracelet/x/ansi"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

func (c *decidingClient) AnswerQuestions(_ context.Context, questionRequestID string, answers models.QuestionAnswers) (models.QuestionAnswersResult, error) {
	c.answers = append(c.answers, answers)
	return models.QuestionAnswersResult{QuestionRequestID: questionRequestID, Continuation: c.continuation}, c.err
}

func questionRequest(id string, headers ...string) models.ToolQuestionRequestEvent {
	if len(headers) == 0 {
		headers = []string{"Scope"}
	}
	request := models.ToolQuestionRequestEvent{QuestionRequestID: id, ToolCallID: "call-" + id}
	for _, header := range headers {
		request.Questions = append(request.Questions, models.ToolQuestion{
			ID:       strings.ToLower(header),
			Header:   header,
			Question: "Which " + strings.ToLower(header) + "?",
			Options: []models.ToolQuestionOption{
				{Label: header + " A", Description: "The first choice."},
				{Label: header + " B", Description: "The second choice."},
			},
		})
	}
	return request
}

func cardEntry(t *testing.T, m Model, id string) string {
	t.Helper()
	for _, e := range m.viewport.entries {
		if e.kind == entryCard && e.cardID == id {
			return stripANSI(e.rendered)
		}
	}
	t.Fatalf("no entry for request %s", id)
	return ""
}

func TestQuestionCardAnswersWithAnOption(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, questionRequest("q1"))
	card := cardEntry(t, m, "q1")
	for _, want := range []string{"Question: Scope", "Which scope?", "> 1. Scope A: The first choice.", "2. Scope B: The second choice.", "Other: type your own answer"} {
		if !strings.Contains(card, want) {
			t.Fatalf("card lacks %q:\n%s", want, card)
		}
	}

	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyDown})
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if !strings.Contains(cardEntry(t, m, "q1"), "Sending your answer") {
		t.Fatal("card does not show the answer in flight")
	}
	m = decide(t, m, cmd)
	want := []models.QuestionAnswers{{Answers: []models.ToolQuestionAnswer{{QuestionID: "scope", OptionLabels: []string{"Scope B"}}}}}
	if !reflect.DeepEqual(client.answers, want) {
		t.Fatalf("answers = %+v, want %+v", client.answers, want)
	}
	if got := cardEntry(t, m, "q1"); got != "● Answered: Scope: Scope B" {
		t.Fatalf("record = %q", got)
	}
	if !m.isStreaming || m.activeQuestion() >= 0 {
		t.Fatal("the answer must close the card for input and keep the stream")
	}
	m = receive(t, m, ch, models.ToolQuestionResolvedEvent{QuestionRequestID: "q1", Outcome: "answered", AnsweredVia: "card", Answers: want[0].Answers})
	if got := cardEntry(t, m, "q1"); got != "● Answered: Scope: Scope B" || len(m.questions) != 0 {
		t.Fatalf("resolved packet changed the record: %q", got)
	}
}

func TestQuestionCardStepsThroughItsQuestionsAndTakesAnOwnAnswer(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, questionRequest("q1", "Scope", "Region"))
	if !strings.Contains(cardEntry(t, m, "q1"), "Question 1 of 2: Scope") {
		t.Fatalf("card = %s", cardEntry(t, m, "q1"))
	}
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if cmd != nil || len(client.answers) != 0 {
		t.Fatal("the first answer of two must not send")
	}
	card := cardEntry(t, m, "q1")
	if !strings.Contains(card, "Question 2 of 2: Region") || !strings.Contains(card, "Scope: Scope A") {
		t.Fatalf("card does not show the next question and the earlier answer:\n%s", card)
	}

	// Other: the next line typed in the input answers the question.
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyDown})
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyDown})
	m, cmd = press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if cmd != nil || !strings.Contains(cardEntry(t, m, "q1"), "Type your answer and press enter") {
		t.Fatalf("Other does not ask for an answer:\n%s", cardEntry(t, m, "q1"))
	}
	m.input.textInput.SetValue("EU only")
	m, cmd = press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m = decide(t, m, cmd)
	want := []models.QuestionAnswers{{Answers: []models.ToolQuestionAnswer{
		{QuestionID: "scope", OptionLabels: []string{"Scope A"}},
		{QuestionID: "region", UserNote: "EU only"},
	}}}
	if !reflect.DeepEqual(client.answers, want) || m.input.textInput.Value() != "" {
		t.Fatalf("answers = %+v, draft = %q", client.answers, m.input.textInput.Value())
	}
	if got := cardEntry(t, m, "q1"); got != "● Answered: Scope: Scope A; Region: EU only" {
		t.Fatalf("record = %q", got)
	}
}

func TestTypedReplyAnswersEveryQuestionOfTheResponse(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: 2})
	m = receive(t, m, ch, questionRequest("q1"))
	m = receive(t, m, ch, questionRequest("q2", "Region"))
	m.input.textInput.SetValue("Only Ana and Raj")

	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m = decide(t, m, cmd)
	if want := []models.QuestionAnswers{{Message: "Only Ana and Raj"}}; !reflect.DeepEqual(client.answers, want) {
		t.Fatalf("answers = %+v, want %+v", client.answers, want)
	}
	for id, title := range map[string]string{"q1": "Scope", "q2": "Region"} {
		if got := cardEntry(t, m, id); got != "● Answered in the chat: "+title+"\n❯ Only Ana and Raj" {
			t.Fatalf("record of %s = %q", id, got)
		}
	}
	m = receive(t, m, ch, models.ToolQuestionResolvedEvent{QuestionRequestID: "q1", Outcome: "answered", AnsweredVia: "message", Message: "Only Ana and Raj"})
	if got := cardEntry(t, m, "q1"); got != "● Answered in the chat: Scope\n❯ Only Ana and Raj" {
		t.Fatalf("record = %q", got)
	}
}

func TestTypedReplyWhileAnApprovalWaitsKeepsTheDraft(t *testing.T) {
	client := &decidingClient{err: &api.OnyxAPIError{StatusCode: 409, ErrorCode: api.ErrorCodeApprovalPending, Detail: "Approve or reject"}}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, questionRequest("q1"))
	m.input.textInput.SetValue("Only Ana")
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m = decide(t, m, cmd)
	if m.input.textInput.Value() != "Only Ana" || len(m.questions) != 1 || m.activeQuestion() != 0 {
		t.Fatalf("the refused reply must keep the draft and the card: draft=%q", m.input.textInput.Value())
	}
	if last := m.viewport.entries[len(m.viewport.entries)-1]; !strings.Contains(last.content, "Approve or reject the tool call first") {
		t.Fatalf("no warning, last entry %q", last.content)
	}
}

func TestApprovalTakesInputBeforeAQuestion(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, approvalRequest("a1"))
	m = receive(t, m, ch, questionRequest("q1"))
	if !strings.Contains(cardEntry(t, m, "q1"), "Waits for the request above") {
		t.Fatal("the question must wait for the approval")
	}
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m = decide(t, m, cmd)
	if len(client.decisions) != 1 || len(client.answers) != 0 {
		t.Fatalf("decisions = %v, answers = %v", client.decisions, client.answers)
	}
	if !strings.Contains(cardEntry(t, m, "q1"), "> 1. Scope A") {
		t.Fatal("the question did not become active after the decision")
	}
}

func TestStoppedQuestionShowsNotAnswered(t *testing.T) {
	m, ch := streamingModel(&decidingClient{})
	m = receive(t, m, ch, questionRequest("q1"))
	if !strings.Contains(cardEntry(t, m, "q1"), "esc stop the response") {
		t.Fatal("a running response that asks can be stopped")
	}
	m = receive(t, m, ch, models.ToolQuestionResolvedEvent{QuestionRequestID: "q1", Outcome: "cancelled"})
	if got := cardEntry(t, m, "q1"); got != "● Not answered: Scope" {
		t.Fatalf("record = %q", got)
	}
}

func TestQuestionAnsweredElsewhereShowsNoLongerWaiting(t *testing.T) {
	client := &decidingClient{err: &api.OnyxAPIError{StatusCode: 409, ErrorCode: "CONFLICT", Detail: "already answered"}}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, questionRequest("q1"))
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m = decide(t, m, cmd)
	if got := cardEntry(t, m, "q1"); got != "● No longer waiting: Scope" {
		t.Fatalf("record = %q", got)
	}
}

// questionSession is a saved session whose response 2 waits for q1.
func questionSession(t *testing.T) *models.ChatSessionDetailResponse {
	t.Helper()
	request, err := json.Marshal(questionRequest("q1"))
	if err != nil {
		t.Fatal(err)
	}
	var obj map[string]any
	if err := json.Unmarshal(request, &obj); err != nil {
		t.Fatal(err)
	}
	obj["type"] = "tool_question_request"
	return &models.ChatSessionDetailResponse{
		ChatSessionID: waitingSessionID,
		Messages: []models.ChatMessageDetail{
			{MessageID: 1, MessageType: "user", Message: "draft the report"},
			{MessageID: 2, MessageType: "assistant", Message: "One question first."},
		},
		Packets: [][]json.RawMessage{{
			savedPacket(t, map[string]any{"type": "message_delta", "content": "One question first."}),
			savedPacket(t, obj),
			savedPacket(t, map[string]any{"type": "stop", "stop_reason": "awaiting_user"}),
		}},
	}
}

func TestQuestionThatParksTheResponseFollowsTheContinuationAfterTheAnswer(t *testing.T) {
	client := &resumingClient{running: make(chan models.StreamEvent, 8)}
	m, ch := streamingModel(client)
	session := waitingSessionID
	m.chatSessionID = &session
	m.viewport.startAgent()
	m = receive(t, m, ch, models.MessageIDEvent{ReservedAgentMessageID: 2})
	m = receive(t, m, ch, models.MessageDeltaEvent{Content: "One question first."})
	m = receive(t, m, ch, questionRequest("q1"))
	reason := models.StopReasonAwaitingUser
	m = receive(t, m, ch, models.StopEvent{StopReason: &reason})
	if strings.Contains(cardEntry(t, m, "q1"), "esc stop the response") {
		t.Fatal("the card offers Stop for a response that waits")
	}
	updated, _ := m.Update(StreamDoneMsg{Channel: ch})
	updated, _ = updated.(Model).Update(sessionReadyMsg{sessionID: waitingSessionID, channel: ch})
	m = updated.(Model)
	if m.isStreaming || m.activeQuestion() != 0 {
		t.Fatal("the card is not actionable after the stream stopped")
	}

	client.continuation = &models.ChatStream{StreamID: 3, ResponseIDs: []int{2}}
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m, _ = run(t, m, cmd)
	if len(client.requests) != 1 || *client.requests[0].streamID != 3 || client.requests[0].cursor != 0 || m.streamCh != client.running {
		t.Fatalf("requests = %+v, want stream 3 from cursor 0", client.requests)
	}
	answered := models.ToolQuestionResolvedEvent{QuestionRequestID: "q1", Outcome: "answered", AnsweredVia: "card", Answers: []models.ToolQuestionAnswer{{QuestionID: "scope", OptionLabels: []string{"Scope A"}}}}
	for _, event := range []models.StreamEvent{
		models.StreamCursorEvent{StreamID: 3},
		models.MessageIDEvent{ReservedAgentMessageID: 2},
		models.MessageDeltaEvent{Content: "One question first."},
		questionRequest("q1"),
		answered,
		models.ReplayEndEvent{},
		answered,
		models.MessageDeltaEvent{Content: "Drafted."},
	} {
		m = receive(t, m, client.running, event)
	}
	view := stripANSI(m.viewport.view(40))
	if strings.Count(view, "One question first.") != 1 || !strings.Contains(view, "Drafted.") || strings.Count(view, "Answered: Scope: Scope A") != 1 || len(m.questions) != 0 {
		t.Fatalf("the continuation does not replace the response once:\n%s", view)
	}
}

func TestResumingASessionThatWaitsForAnAnswerShowsTheQuestion(t *testing.T) {
	client := &resumingClient{stops: make(chan int, 1)}
	m := NewModel(config.DefaultConfig(), client)
	m, _ = run(t, m, func() tea.Msg { return SessionResumedMsg{Detail: questionSession(t)} })
	if !strings.Contains(cardEntry(t, m, "q1"), "> 1. Scope A") {
		t.Fatal("the waiting question cannot be answered")
	}
	for _, key := range []tea.KeyPressMsg{{Code: tea.KeyEscape}, {Code: 'c', Mod: tea.ModCtrl}} {
		updated, cmd := m.handleKey(key)
		m = updated.(Model)
		if cmd != nil || m.stopRequested {
			t.Fatalf("%s acted on a waiting response", key.String())
		}
	}

	// A session load that shows the answer of another client closes the card.
	saved := questionSession(t)
	saved.Packets[0] = append(saved.Packets[0][:2],
		savedPacket(t, map[string]any{"type": "tool_question_resolved", "question_request_id": "q1", "outcome": "answered", "answered_via": "message", "message": "Only Ana"}))
	m = m.showSavedRequests(saved.ApprovalsVersion, readSavedRequests(saved))
	if got := cardEntry(t, m, "q1"); got != "● Answered in the chat: Scope\n❯ Only Ana" || len(m.questions) != 0 {
		t.Fatalf("record = %q", got)
	}
}

func TestResumingASessionShowsTheRecordOfAnAnsweredQuestion(t *testing.T) {
	saved := questionSession(t)
	saved.Packets[0] = append(saved.Packets[0][:2],
		savedPacket(t, map[string]any{"type": "tool_question_resolved", "question_request_id": "q1", "outcome": "answered", "answered_via": "message", "message": "Only Ana"}),
		savedPacket(t, map[string]any{"type": "stop", "stop_reason": "finished"}))
	m := NewModel(config.DefaultConfig(), &resumingClient{})
	m, _ = run(t, m, func() tea.Msg { return SessionResumedMsg{Detail: saved} })
	if got := cardEntry(t, m, "q1"); got != "● Answered in the chat: Scope\n❯ Only Ana" || len(m.questions) != 0 {
		t.Fatalf("record = %q", got)
	}
	view := stripANSI(m.viewport.view(40))
	if strings.Index(view, "Only Ana") > strings.Index(view, "One question first.") {
		t.Fatalf("the record does not come before the response's text:\n%s", view)
	}
}

func TestALateReplyOfAnotherChatLeavesTheCardsAndDraftAlone(t *testing.T) {
	for _, err := range []error{nil, errors.New("timeout")} {
		m := NewModel(config.DefaultConfig(), &resumingClient{})
		other := "other-session"
		m.chatSessionID = &other
		m.questions = []questionCard{{request: questionRequest("q9"), sending: true}}
		entries := len(m.viewport.entries)
		updated, _ := m.handleQuestionsAnswered(questionsAnsweredMsg{
			sessionID:  waitingSessionID,
			requestIDs: []string{"q1"},
			answers:    models.QuestionAnswers{Message: "Only Ana"},
			err:        err,
		})
		got := updated.(Model)
		if card := got.questions[0]; !card.sending || card.decided != "" {
			t.Fatalf("err=%v changed the other chat's card: %+v", err, card)
		}
		if got.input.textInput.Value() != "" {
			t.Fatalf("err=%v put the reply in the other chat's input: %q", err, got.input.textInput.Value())
		}
		for _, entry := range got.viewport.entries[entries:] {
			if entry.kind != entryCard {
				t.Fatalf("err=%v showed a line in the other chat: %q", err, entry.content)
			}
		}
	}
}

func TestQuestionCardWrapsLongChoices(t *testing.T) {
	request := questionRequest("q1")
	for _, option := range []models.ToolQuestionOption{
		{Label: "Scope A", Description: strings.Repeat("word ", 30) + "end"},
		// One word fills a continuation row.
		{Label: "A", Description: "abcdefghijklmnopqrstuvwxyz0123456"},
	} {
		request.Questions[0].Options[0] = option
		for _, selected := range []int{0, 1} {
			card := stripANSI(renderQuestionCard(questionCard{request: request, selected: selected}, true, false, 40))
			choices, _, _ := strings.Cut(card, "Other:")
			if strings.Contains(choices, "…") || !strings.Contains(strings.Join(strings.Fields(choices), ""), strings.Join(strings.Fields(option.Description), "")) {
				t.Fatalf("a choice is cut off:\n%s", card)
			}
			for _, line := range strings.Split(card, "\n") {
				if ansi.StringWidth(line) > 39 {
					t.Fatalf("line wider than the terminal: %q", line)
				}
			}
		}
	}
}

func TestQuestionCardStripsHostileContent(t *testing.T) {
	m, ch := streamingModel(&decidingClient{})
	request := questionRequest("q1")
	request.Questions[0].Header = "Sco\x1b]52;c;ZWNobyBoaQ==\x07pe"
	request.Questions[0].Question = "Which\x1b[2J scope?\rnow"
	request.Questions[0].Options[0].Label = "A\x1b]8;;https://evil\x1b\\"
	m = receive(t, m, ch, request)
	var rendered string
	for _, e := range m.viewport.entries {
		if e.kind == entryCard {
			rendered = e.rendered
		}
	}
	for _, injected := range []string{"\x1b]52;", "\x1b]8;", "\x1b[2J", "\x07", "\r"} {
		if strings.Contains(rendered, injected) {
			t.Fatalf("card keeps the injected sequence %q: %q", injected, rendered)
		}
	}
}

func TestTypedOptionNumberChoosesTheOption(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, questionRequest("q1", "Scope", "Region"))
	m.input.textInput.SetValue("2")
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if cmd != nil || len(client.answers) != 0 || m.input.textInput.Value() != "" {
		t.Fatalf("a typed option number must answer the step, not send a reply: answers=%+v", client.answers)
	}
	// A number that names no option is a reply.
	m.input.textInput.SetValue("7")
	m, cmd = press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	decide(t, m, cmd)
	want := []models.QuestionAnswers{{Message: "7"}}
	if !reflect.DeepEqual(client.answers, want) {
		t.Fatalf("answers = %+v, want %+v", client.answers, want)
	}
	if got := m.questions[0].answers; !reflect.DeepEqual(got, []models.ToolQuestionAnswer{{QuestionID: "scope", OptionLabels: []string{"Scope B"}}}) {
		t.Fatalf("step answers = %+v", got)
	}
}

func TestOwnAnswerKeepsALeadingSlash(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, questionRequest("q1"))
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyUp})
	for range 2 {
		m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyDown})
	}
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m.input.textInput.SetValue("/var/log")
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	decide(t, m, cmd)
	want := []models.QuestionAnswers{{Answers: []models.ToolQuestionAnswer{{QuestionID: "scope", UserNote: "/var/log"}}}}
	if !reflect.DeepEqual(client.answers, want) {
		t.Fatalf("answers = %+v, want %+v", client.answers, want)
	}
}

func TestOwnAnswerThatNamesACommandIsTheAnswer(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, questionRequest("q1"))
	for range 2 {
		m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyDown})
	}
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m.splashShown = true
	m.input.textInput.Focus()
	updated, _ := m.Update(tea.PasteMsg{Content: "/qui"})
	m = updated.(Model)
	if m.input.textInput.Value() != "/qui" || m.input.menuVisible {
		t.Fatal("the command menu opened for a pasted answer after Other")
	}
	// Any key that reaches the input refreshes the command menu.
	m, _ = press(t, m, tea.KeyPressMsg{Code: 't', Text: "t"})
	if m.input.menuVisible {
		t.Fatal("the command menu opened for an answer after Other")
	}
	m.input.textInput.SetValue("/quit")
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	decide(t, m, cmd)
	want := []models.QuestionAnswers{{Answers: []models.ToolQuestionAnswer{{QuestionID: "scope", UserNote: "/quit"}}}}
	if !reflect.DeepEqual(client.answers, want) {
		t.Fatalf("answers = %+v, want %+v", client.answers, want)
	}
}

func TestBackgroundAgentRequestDoesNotBlockTheQuestion(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, agentRequest("b1"))
	m = receive(t, m, ch, questionRequest("q1"))
	if !strings.Contains(cardEntry(t, m, "q1"), "> 1. Scope A") {
		t.Fatalf("the question waits for a background agent's request:\n%s", cardEntry(t, m, "q1"))
	}
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	decide(t, m, cmd)
	if len(client.answers) != 1 || len(client.decisions) != 0 {
		t.Fatalf("answers = %+v, decisions = %v", client.answers, client.decisions)
	}
}

func TestRepeatedEnterWhileTheAnswerIsSentDoesNotDecideABackgroundRequest(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, agentRequest("b1"))
	m = receive(t, m, ch, questionRequest("q1"))
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if !m.questions[0].sending {
		t.Fatal("the answer is not being sent")
	}
	m, cmd := press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if cmd != nil || m.approvals[0].sending != "" {
		t.Fatalf("a second enter decided the background request")
	}
}

func TestAnswerAfterOtherDoesNotDecideABackgroundRequest(t *testing.T) {
	client := &decidingClient{}
	m, ch := streamingModel(client)
	m = receive(t, m, ch, agentRequest("b1"))
	m = receive(t, m, ch, questionRequest("q1"))
	for range 2 {
		m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyDown})
	}
	m, _ = press(t, m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m, cmd := press(t, m, tea.KeyPressMsg{Code: 'a', Text: "a"})
	if cmd != nil {
		decide(t, m, cmd)
	}
	if len(client.decisions) != 0 || m.approvals[0].sending != "" {
		t.Fatalf("typing an answer decided the background request: %v", client.decisions)
	}
}
