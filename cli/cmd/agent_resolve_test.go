package cmd

import (
	"context"
	"errors"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

type fakeAgentLister struct {
	agents []models.AgentSummary
}

func (f fakeAgentLister) ListAgents(context.Context) ([]models.AgentSummary, error) {
	return f.agents, nil
}

func TestResolveAgentSelection(t *testing.T) {
	client := fakeAgentLister{
		agents: []models.AgentSummary{
			{ID: 5, Name: "Support Agent", IsVisible: true},
		},
	}

	t.Run("agent_id_explicit", func(t *testing.T) {
		id, explicit, err := resolveAgentSelection(context.Background(), client, 3, true, "", false, 7)
		if err != nil {
			t.Fatalf("resolveAgentSelection: %v", err)
		}
		if id != 3 || !explicit {
			t.Errorf("got id=%d explicit=%v, want 3 true", id, explicit)
		}
	})

	t.Run("agent_name_resolves", func(t *testing.T) {
		id, explicit, err := resolveAgentSelection(context.Background(), client, 0, false, "support", true, 7)
		if err != nil {
			t.Fatalf("resolveAgentSelection: %v", err)
		}
		if id != 5 || !explicit {
			t.Errorf("got id=%d explicit=%v, want 5 true", id, explicit)
		}
	})

	t.Run("mutually_exclusive", func(t *testing.T) {
		_, _, err := resolveAgentSelection(context.Background(), client, 1, true, "support", true, 0)
		if err == nil {
			t.Fatal("expected error")
		}
		var exitErr *exitcodes.ExitError
		if !errors.As(err, &exitErr) || exitErr.Code != exitcodes.BadRequest {
			t.Fatalf("got %T %v, want BadRequest ExitError", err, err)
		}
	})

	t.Run("default_when_unset", func(t *testing.T) {
		id, explicit, err := resolveAgentSelection(context.Background(), client, 0, false, "", false, 7)
		if err != nil {
			t.Fatalf("resolveAgentSelection: %v", err)
		}
		if id != 7 || explicit {
			t.Errorf("got id=%d explicit=%v, want 7 false", id, explicit)
		}
	})

	t.Run("empty_agent_name", func(t *testing.T) {
		_, _, err := resolveAgentSelection(context.Background(), client, 0, false, "  ", true, 0)
		if err == nil {
			t.Fatal("expected error")
		}
		var exitErr *exitcodes.ExitError
		if !errors.As(err, &exitErr) || exitErr.Code != exitcodes.BadRequest {
			t.Fatalf("got %T %v, want BadRequest ExitError", err, err)
		}
	})
}
