package tui

import (
	"context"
	"maps"
	"slices"
	"strconv"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/approval"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/question"
	"github.com/onyx-dot-app/onyx/cli/internal/sanitize"
)

// questionCard is a question request whose outcome the server has not
// reported yet. The user answers its questions one at a time.
type questionCard struct {
	request models.ToolQuestionRequestEvent
	// responseID is the response that waits for the answers, or 0 when
	// unknown.
	responseID int
	// step is the question that the user answers now.
	step int
	// selected is the row of the step: an option, or Other after them.
	selected int
	// noting marks Other chosen: the next line typed in the input answers
	// the step.
	noting bool
	// answers holds the answers to the questions before step.
	answers []models.ToolQuestionAnswer
	sending bool
	// decided describes the outcome of this client's answer, and message is
	// the text that it typed. The card shows them until the server's
	// resolution or a session load replaces them.
	decided string
	message string
}

// questionsAnsweredMsg carries the server's reply to answers.
type questionsAnsweredMsg struct {
	// sessionID is the chat that showed the request, or empty.
	sessionID string
	// responseID is the response that waits for the answers.
	responseID int
	// streams is the model's stream count when the answers were sent.
	streams int
	// requestIDs are the cards that wait for this reply.
	requestIDs []string
	answers    models.QuestionAnswers
	result     models.QuestionAnswersResult
	err        error
}

// renderQuestionCard renders a question request. Only the active card takes
// input. stoppable offers Stop for the running response that waits.
func renderQuestionCard(card questionCard, active, stoppable bool, width int) string {
	if card.decided != "" {
		return questionRecord(card.decided, card.message)
	}
	questions := card.request.Questions
	if len(questions) == 0 {
		return questionRecord("Question: "+question.Title(card.request), "")
	}
	step := min(card.step, len(questions)-1)
	current := questions[step]
	title := "● Question: " + sanitize.Line(current.Header)
	if len(questions) > 1 {
		title = "● Question " + strconv.Itoa(step+1) + " of " + strconv.Itoa(len(questions)) + ": " + sanitize.Line(current.Header)
	}
	lines := []string{warnStyle.Render(title)}
	if answered := question.Answered(card.request, card.answers); answered != "" {
		lines = append(lines, dimInfoStyle.Render("    "+answered))
	}
	wrapAt := max(width-5, 16)
	for _, row := range strings.Split(ansi.Wrap(sanitize.Line(current.Question), wrapAt, ""), "\n") {
		lines = append(lines, "    "+row)
	}
	rows := make([]string, 0, len(current.Options)+1)
	for i, option := range current.Options {
		rows = append(rows, strconv.Itoa(i+1)+". "+question.Option(option))
	}
	rows = append(rows, "Other: type your own answer")
	// Choices wrap under their text, so no part of a choice is hidden.
	rowLines := func(row string) []string {
		// A continuation row has a 7-column indent and keeps a 1-column margin.
		return strings.Split(ansi.Wrap(row, max(width-8, 14), ""), "\n")
	}
	switch {
	case !active:
		for _, row := range rows[:len(rows)-1] {
			for j, line := range rowLines(row) {
				if j == 0 {
					lines = append(lines, "    "+line)
				} else {
					lines = append(lines, "       "+line)
				}
			}
		}
		lines = append(lines, dimInfoStyle.Render("    Waits for the request above."))
	case card.sending:
		lines = append(lines, dimInfoStyle.Render("    Sending your answer…"))
	case card.noting:
		lines = append(lines, "  "+lipgloss.NewStyle().Foreground(accentColor).Bold(true).Render("> Other"))
		lines = append(lines, dimInfoStyle.Render("    Type your answer and press enter • esc back"))
	default:
		selected := lipgloss.NewStyle().Foreground(accentColor).Bold(true)
		for i, row := range rows {
			for j, line := range rowLines(row) {
				switch {
				case i == card.selected && j == 0:
					lines = append(lines, "  "+selected.Render("> "+line))
				case i == card.selected:
					lines = append(lines, "  "+selected.Render("     "+line))
				case j == 0:
					lines = append(lines, "    "+line)
				default:
					lines = append(lines, "       "+line)
				}
			}
		}
		hint := "    ↑↓ or a number • enter confirm • or type a reply"
		if stoppable {
			hint += " • esc stop the response"
		}
		lines = append(lines, dimInfoStyle.Render(hint))
	}
	for i := range lines {
		lines[i] = ansi.Truncate(lines[i], max(width-1, 20), "…")
	}
	return strings.Join(lines, "\n")
}

// questionRecord is the record of how a request ended. A typed answer shows
// as the user's message under it.
func questionRecord(outcome, message string) string {
	record := infoStyle.Render("● " + outcome)
	if message != "" {
		record += "\n" + userPrefixStyle.Render("❯ ") + sanitize.Terminal(message)
	}
	return record
}

func (m Model) questionIndex(questionRequestID string) int {
	for i, card := range m.questions {
		if card.request.QuestionRequestID == questionRequestID {
			return i
		}
	}
	return -1
}

// activeQuestion is the index of the oldest card that waits for this
// client's answer, or -1. An undecided approval request of the chat's own
// agent for the same response takes input first; a background agent's
// request does not.
func (m Model) activeQuestion() int {
	for i, card := range m.questions {
		if card.decided != "" {
			continue
		}
		for _, request := range m.approvals {
			if request.decided == "" && request.request.AgentName == "" &&
				(request.responseID == card.responseID || request.responseID == 0 || card.responseID == 0) {
				return -1
			}
		}
		return i
	}
	return -1
}

func (m Model) renderQuestions() {
	active := m.activeQuestion()
	running := m.isStreaming && !m.awaitingUser
	for i, card := range m.questions {
		m.viewport.setCard(card.request.QuestionRequestID, renderQuestionCard(card, i == active, running, m.viewport.width))
	}
}

// resolveQuestion replaces a card with the record of how it ended.
func (m Model) resolveQuestion(index int, outcome, message string) Model {
	id := m.questions[index].request.QuestionRequestID
	resolved := maps.Clone(m.resolvedRequests)
	if resolved == nil {
		resolved = map[string]bool{}
	}
	resolved[id] = true
	m.resolvedRequests = resolved
	m.viewport.setCard(id, questionRecord(outcome, message))
	m.questions = append(m.questions[:index:index], m.questions[index+1:]...)
	m.renderCards()
	return m
}

// answerStep records the answer to the active card's current question, and
// sends the card's answers after its last question.
func (m Model) answerStep(index int, answer models.ToolQuestionAnswer) (Model, tea.Cmd) {
	card := &m.questions[index]
	card.answers = append(card.answers[:card.step:card.step], answer)
	card.step++
	card.selected, card.noting = 0, false
	if card.step < len(card.request.Questions) {
		m.renderCards()
		return m, nil
	}
	return m.sendAnswers(index, models.QuestionAnswers{Answers: card.answers})
}

// sendAnswers sends the answers of a card. A message answers every card of
// the card's response, so each of them waits for the reply.
func (m Model) sendAnswers(index int, answers models.QuestionAnswers) (Model, tea.Cmd) {
	responseID := m.questions[index].responseID
	var requestIDs []string
	for i := range m.questions {
		if i == index || (answers.Message != "" && m.questions[i].responseID == responseID && m.questions[i].decided == "") {
			m.questions[i].sending = true
			requestIDs = append(requestIDs, m.questions[i].request.QuestionRequestID)
		}
	}
	m.renderCards()
	client, id, streams := m.client, m.questions[index].request.QuestionRequestID, m.streams
	sessionID := ""
	if m.chatSessionID != nil {
		sessionID = *m.chatSessionID
	}
	return m, func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		result, err := client.AnswerQuestions(ctx, id, answers)
		return questionsAnsweredMsg{sessionID: sessionID, responseID: responseID, streams: streams, requestIDs: requestIDs, answers: answers, result: result, err: err}
	}
}

// takesOwnAnswer reports whether the active question takes an answer after
// Other. The draft is then the answer as typed, also when it starts with a
// slash, so no command menu opens and no approval shortcut applies.
func (m Model) takesOwnAnswer() bool {
	index := m.activeQuestion()
	return index >= 0 && m.questions[index].noting
}

func (m Model) handleQuestionsAnswered(msg questionsAnsweredMsg) (tea.Model, tea.Cmd) {
	noLongerWaiting := api.IsNoLongerWaiting(msg.err)
	// Only the cards that sent the reply change; a reply whose cards are
	// gone, for example after the user opened another chat, shows nothing.
	matched := false
	for i := range m.questions {
		card := &m.questions[i]
		if !card.sending || !slices.Contains(msg.requestIDs, card.request.QuestionRequestID) {
			continue
		}
		matched = true
		card.sending = false
		switch {
		case msg.err == nil && msg.answers.Message != "":
			card.decided = "Answered in the chat: " + question.Title(card.request)
			card.message = msg.answers.Message
		case msg.err == nil:
			card.decided = "Answered: " + question.Answered(card.request, msg.answers.Answers)
		case noLongerWaiting:
			card.decided = approval.NoLongerWaiting + ": " + question.Title(card.request)
		default:
			// The user answers the card again from its first question.
			card.step, card.selected, card.noting, card.answers = 0, 0, false, nil
		}
	}
	switch {
	case !matched:
	case api.IsApprovalPending(msg.err):
		m.viewport.addWarning("Approve or reject the tool call first. Your reply is kept.")
	case msg.err != nil && !noLongerWaiting:
		m.viewport.addError("Could not send the answer: " + msg.err.Error())
	}
	if matched && msg.err != nil && !noLongerWaiting && msg.answers.Message != "" && m.input.textInput.Value() == "" {
		m.input.textInput.SetValue(msg.answers.Message)
	}
	m.renderCards()
	return m.continueAfterAnswer(msg.sessionID, msg.responseID, msg.streams, false, msg.result.Continuation, msg.err)
}

// handleQuestionKey applies a key to the active card. Enter with a draft
// that is an option's number chooses the option. Other drafts are the
// answer to the current question after Other, and otherwise the reply to
// the response's questions. Slash commands keep working, except after
// Other, where the draft is the answer as typed.
func (m Model) handleQuestionKey(msg tea.KeyPressMsg) (Model, tea.Cmd, bool) {
	index := m.activeQuestion()
	if index < 0 {
		return m, nil, false
	}
	card := &m.questions[index]
	if card.sending {
		// A repeated or held confirm while the answer is sent must not
		// reach a background agent's approval card.
		switch msg.String() {
		case "enter", "up", "down":
			return m, nil, true
		}
		return m, nil, false
	}
	if len(card.request.Questions) == 0 {
		return m, nil, false
	}
	current := card.request.Questions[card.step]
	draft := strings.TrimSpace(m.input.textInput.Value())
	switch msg.String() {
	case "up", "down":
		if card.noting {
			return m, nil, false
		}
		if msg.String() == "up" && card.selected > 0 {
			card.selected--
		}
		if msg.String() == "down" && card.selected < len(current.Options) {
			card.selected++
		}
		m.renderCards()
		return m, nil, true
	case "esc":
		if !card.noting {
			return m, nil, false
		}
		card.noting = false
		m.renderCards()
		return m, nil, true
	case "enter":
		if strings.HasPrefix(draft, "/") && !card.noting {
			return m, nil, false
		}
		switch {
		case draft != "":
			m.input.textInput.SetValue("")
			if card.noting {
				m, cmd := m.answerStep(index, models.ToolQuestionAnswer{QuestionID: current.ID, UserNote: draft})
				return m, cmd, true
			}
			if answer := question.Parse(current, draft); answer.OptionLabel != "" {
				m, cmd := m.answerStep(index, answer)
				return m, cmd, true
			}
			m, cmd := m.sendAnswers(index, models.QuestionAnswers{Message: draft})
			return m, cmd, true
		case card.noting:
			return m, nil, true
		case card.selected == len(current.Options):
			card.noting = true
			m.renderCards()
			return m, nil, true
		default:
			m, cmd := m.answerStep(index, models.ToolQuestionAnswer{QuestionID: current.ID, OptionLabel: current.Options[card.selected].Label})
			return m, cmd, true
		}
	}
	return m, nil, false
}
