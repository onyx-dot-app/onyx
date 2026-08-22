package tui

import (
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

func testModelOptions() []models.ModelOption {
	return []models.ModelOption{
		{
			SelectedModel: models.SelectedModel{ConfigurationID: 10, ModelName: "gpt-4o", DisplayName: "GPT-4o"},
			ProviderLabel: "OpenAI",
		},
		{
			SelectedModel:  models.SelectedModel{ConfigurationID: 20, ModelName: "claude-opus-5"},
			ProviderLabel:  "Claude (Anthropic)",
			IsAgentDefault: true,
		},
		{
			SelectedModel: models.SelectedModel{ConfigurationID: 21, ModelName: "claude-sonnet-5"},
			ProviderLabel: "Claude (Anthropic)",
		},
	}
}

func TestFindModel(t *testing.T) {
	options := testModelOptions()

	tests := []struct {
		name string
		arg  string
		want string // model name, or "" when no match is expected
	}{
		{"exact model name", "gpt-4o", "gpt-4o"},
		{"case insensitive", "GPT-4O", "gpt-4o"},
		{"display name", "GPT-4o", "gpt-4o"},
		{"unique prefix", "claude-opus", "claude-opus-5"},
		{"ambiguous prefix", "claude", ""},
		{"no match", "gemini", ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := findModel(options, tt.arg)
			if tt.want == "" {
				if got != nil {
					t.Fatalf("findModel(%q) = %q, want no match", tt.arg, got.ModelName)
				}
				return
			}
			if got == nil {
				t.Fatalf("findModel(%q) = no match, want %q", tt.arg, tt.want)
			}
			if got.ModelName != tt.want {
				t.Errorf("findModel(%q) = %q, want %q", tt.arg, got.ModelName, tt.want)
			}
		})
	}
}

func TestRefreshModelStatus(t *testing.T) {
	m := Model{modelOptions: testModelOptions(), status: newStatusBar()}

	// With no selection the status bar shows the agent's own default.
	m.refreshModelStatus()
	if m.status.modelName != "claude-opus-5" {
		t.Errorf("model status = %q, want the agent default claude-opus-5", m.status.modelName)
	}

	// An explicit selection wins, and prefers the display name.
	m.selectedModel = &models.SelectedModel{ModelName: "gpt-4o", DisplayName: "GPT-4o"}
	m.refreshModelStatus()
	if m.status.modelName != "GPT-4o" {
		t.Errorf("model status = %q, want GPT-4o", m.status.modelName)
	}
}

func TestStatusBarShowsModel(t *testing.T) {
	s := newStatusBar()
	s.setWidth(120)
	s.setAgent("Research")
	s.setModel("GPT-4o")

	view := stripANSI(s.view())
	if !strings.Contains(view, "Research · GPT-4o") {
		t.Errorf("status bar = %q, want it to show the agent and model", view)
	}
}
