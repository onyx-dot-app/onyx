package tui

import (
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
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

func TestResumedSessionStripsControlSequences(t *testing.T) {
	agentName := "Help\x1b]52;c;cm0gLXJm\x07\nDesk"
	m := NewModel(config.DefaultConfig(), nil)
	updated, _ := m.handleSessionResumed(SessionResumedMsg{Detail: &models.ChatSessionDetailResponse{
		ChatSessionID: "abc",
		AgentName:     &agentName,
		Messages: []models.ChatMessageDetail{
			{MessageID: 1, MessageType: "user", Message: "hi\x1b]8;;https://evil\x1b\\there\x07"},
			{MessageID: 2, MessageType: "assistant", Message: "ok\x1b[2J"},
		},
	}})
	m = updated.(Model)

	for _, e := range m.viewport.entries {
		if strings.ContainsAny(e.content, "\x1b\x07") || strings.Contains(e.rendered, "\x1b]") {
			t.Errorf("replayed entry keeps control bytes: content=%q rendered=%q", e.content, e.rendered)
		}
	}
	if m.status.agentName != "Help Desk" {
		t.Errorf("status agent = %q, want %q", m.status.agentName, "Help Desk")
	}
}
