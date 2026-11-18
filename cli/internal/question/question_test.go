package question

import (
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

func TestParse(t *testing.T) {
	q := models.ToolQuestion{ID: "scope", Options: []models.ToolQuestionOption{{Label: "Company"}, {Label: "Team"}}}
	for line, want := range map[string]models.ToolQuestionAnswer{
		"1":        {QuestionID: "scope", OptionLabel: "Company"},
		" 2\n":     {QuestionID: "scope", OptionLabel: "Team"},
		"0":        {QuestionID: "scope", UserNote: "0"},
		"3":        {QuestionID: "scope", UserNote: "3"},
		"-1":       {QuestionID: "scope", UserNote: "-1"},
		"":         {QuestionID: "scope", UserNote: NoAnswer},
		"  \n":     {QuestionID: "scope", UserNote: NoAnswer},
		"EU only":  {QuestionID: "scope", UserNote: "EU only"},
		"2 people": {QuestionID: "scope", UserNote: "2 people"},
	} {
		if got := Parse(q, line); got != want {
			t.Errorf("Parse(%q) = %+v, want %+v", line, got, want)
		}
	}
}
