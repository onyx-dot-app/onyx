// Package question formats the agent's questions and their answers for the
// terminal. Question fields come from the model, so every value passes
// through sanitize.
package question

import (
	"strconv"
	"strings"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/sanitize"
)

// NoAnswer is the note that answers a question when no one can answer it here.
const NoAnswer = "No answer. Continue with your best judgment."

// Title names a question request by the headers of its questions.
func Title(req models.ToolQuestionRequestEvent) string {
	var headers []string
	for _, q := range req.Questions {
		if header := sanitize.Line(q.Header); header != "" {
			headers = append(headers, header)
		}
	}
	if len(headers) == 0 {
		return "Question"
	}
	return strings.Join(headers, ", ")
}

// Option is the line of a question's choice: its label and what it means.
func Option(option models.ToolQuestionOption) string {
	label := sanitize.Line(option.Label)
	if description := sanitize.Line(option.Description); description != "" {
		return label + ": " + description
	}
	return label
}

// Parse reads a line typed at a prompt as the answer to q: the number of an
// option chooses it, other text is a note, and an empty line is NoAnswer.
func Parse(q models.ToolQuestion, line string) models.ToolQuestionAnswer {
	line = strings.TrimSpace(line)
	answer := models.ToolQuestionAnswer{QuestionID: q.ID}
	if n, err := strconv.Atoi(line); err == nil && n >= 1 && n <= len(q.Options) {
		answer.OptionLabel = q.Options[n-1].Label
		return answer
	}
	if line == "" {
		line = NoAnswer
	}
	answer.UserNote = line
	return answer
}

// Unanswered answers every question of req with NoAnswer.
func Unanswered(req models.ToolQuestionRequestEvent) []models.ToolQuestionAnswer {
	answers := make([]models.ToolQuestionAnswer, len(req.Questions))
	for i, q := range req.Questions {
		answers[i] = models.ToolQuestionAnswer{QuestionID: q.ID, UserNote: NoAnswer}
	}
	return answers
}

// Answered describes card answers as "Header: answer", one for each question
// of req, in its order.
func Answered(req models.ToolQuestionRequestEvent, answers []models.ToolQuestionAnswer) string {
	byID := make(map[string]models.ToolQuestionAnswer, len(answers))
	for _, answer := range answers {
		byID[answer.QuestionID] = answer
	}
	var parts []string
	for _, q := range req.Questions {
		answer, ok := byID[q.ID]
		if !ok {
			continue
		}
		var text []string
		for _, value := range []string{answer.OptionLabel, answer.UserNote} {
			if value = sanitize.Line(value); value != "" {
				text = append(text, value)
			}
		}
		parts = append(parts, sanitize.Line(q.Header)+": "+strings.Join(text, ", "))
	}
	return strings.Join(parts, "; ")
}

// Outcome describes how a question request ended.
func Outcome(req models.ToolQuestionRequestEvent, resolved models.ToolQuestionResolvedEvent) string {
	switch {
	case resolved.Outcome != models.QuestionOutcomeAnswered:
		return "Not answered: " + Title(req)
	case resolved.AnsweredVia == models.QuestionAnsweredViaMessage:
		return "Answered in the chat: " + Title(req)
	default:
		if answered := Answered(req, resolved.Answers); answered != "" {
			return "Answered: " + answered
		}
		return "Answered: " + Title(req)
	}
}
