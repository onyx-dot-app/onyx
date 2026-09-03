package tui

import (
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/config"
)

func TestWithSessionAgent(t *testing.T) {
	cfg := config.OnyxCliConfig{DefaultAgentID: 7}
	m := NewModel(cfg, nil)

	if m.agentID != 7 {
		t.Fatalf("default agentID = %d, want 7", m.agentID)
	}

	m = m.WithSessionAgent(42)
	if m.agentID != 42 {
		t.Fatalf("session agentID = %d, want 42", m.agentID)
	}
	if m.config.DefaultAgentID != 7 {
		t.Fatalf("config.DefaultAgentID = %d, want unchanged 7", m.config.DefaultAgentID)
	}
}

func TestWithSessionAgentOnFirstRunModel(t *testing.T) {
	cfg := config.OnyxCliConfig{APIKey: "pat-from-env", DefaultAgentID: 7}
	m := NewFirstRunModel(cfg).WithSessionAgent(42)

	if m.agentID != 42 {
		t.Fatalf("session agentID = %d, want 42", m.agentID)
	}
	if m.startMode != startFirstRun {
		t.Fatalf("startMode = %v, want first-run", m.startMode)
	}
}
