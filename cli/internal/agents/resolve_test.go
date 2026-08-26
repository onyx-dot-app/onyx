package agents

import (
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

func TestResolveByName_ExactMatch(t *testing.T) {
	agents := []models.AgentSummary{
		{ID: 1, Name: "Support Agent"},
		{ID: 2, Name: "Engineering Bot"},
	}

	got, err := ResolveByName(agents, "support agent")
	if err != nil {
		t.Fatalf("ResolveByName: %v", err)
	}
	if got.ID != 1 {
		t.Errorf("ID = %d, want 1", got.ID)
	}
}

func TestResolveByName_UniqueSubstring(t *testing.T) {
	agents := []models.AgentSummary{
		{ID: 1, Name: "Support Agent"},
		{ID: 2, Name: "Engineering Bot"},
	}

	got, err := ResolveByName(agents, "engineer")
	if err != nil {
		t.Fatalf("ResolveByName: %v", err)
	}
	if got.ID != 2 {
		t.Errorf("ID = %d, want 2", got.ID)
	}
}

func TestResolveByName_NoMatch(t *testing.T) {
	agents := []models.AgentSummary{{ID: 1, Name: "Support Agent"}}

	_, err := ResolveByName(agents, "missing")
	if err == nil {
		t.Fatal("expected error for no match")
	}
	if !strings.Contains(err.Error(), "no agent matches") {
		t.Errorf("error = %q, want no-match message", err.Error())
	}
}

func TestResolveByName_Ambiguous(t *testing.T) {
	agents := []models.AgentSummary{
		{ID: 1, Name: "Support Agent"},
		{ID: 2, Name: "Support Lead"},
	}

	_, err := ResolveByName(agents, "support")
	if err == nil {
		t.Fatal("expected ambiguity error")
	}
	if !strings.Contains(err.Error(), "ambiguous") {
		t.Errorf("error = %q, want ambiguity message", err.Error())
	}
}

func TestResolveByName_EmptyName(t *testing.T) {
	_, err := ResolveByName(nil, "  ")
	if err == nil {
		t.Fatal("expected error for empty name")
	}
}
