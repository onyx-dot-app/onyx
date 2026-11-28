package question

import (
	"reflect"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

func TestParse(t *testing.T) {
	q := models.ToolQuestion{ID: "scope", Options: []models.ToolQuestionOption{{Label: "Company"}, {Label: "Team"}}}
	for line, want := range map[string]models.ToolQuestionAnswer{
		"1":        {QuestionID: "scope", OptionLabels: []string{"Company"}},
		" 2\n":     {QuestionID: "scope", OptionLabels: []string{"Team"}},
		"0":        {QuestionID: "scope", UserNote: "0"},
		"3":        {QuestionID: "scope", UserNote: "3"},
		"-1":       {QuestionID: "scope", UserNote: "-1"},
		"":         {QuestionID: "scope", UserNote: NoAnswer},
		"  \n":     {QuestionID: "scope", UserNote: NoAnswer},
		"EU only":  {QuestionID: "scope", UserNote: "EU only"},
		"2 people": {QuestionID: "scope", UserNote: "2 people"},
	} {
		if got := Parse(q, line); !reflect.DeepEqual(got, want) {
			t.Errorf("Parse(%q) = %+v, want %+v", line, got, want)
		}
	}
}

func TestAnsweredListsEveryChosenOption(t *testing.T) {
	req := models.ToolQuestionRequestEvent{Questions: []models.ToolQuestion{{ID: "channels", Header: "Channels"}, {ID: "scope", Header: "Scope"}}}
	answers := []models.ToolQuestionAnswer{
		{QuestionID: "channels", OptionLabels: []string{"Email", "Wiki"}, UserNote: "Teams"},
		{QuestionID: "scope", UserNote: "EU"},
	}
	if got, want := Answered(req, answers), "Channels: Email, Wiki, Teams; Scope: EU"; got != want {
		t.Errorf("Answered = %q, want %q", got, want)
	}
}
