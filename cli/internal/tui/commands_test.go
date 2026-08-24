package tui

import (
	"strings"
	"testing"

	"charm.land/lipgloss/v2"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

func intPtr(v int) *int { return &v }

func strPtr(v string) *string { return &v }

func testProviderResponse() *models.LLMProviderResponse {
	return &models.LLMProviderResponse{
		Providers: []models.LLMProviderDescriptor{
			{
				ID:                  1,
				Name:                strPtr("OpenAI Prod"),
				Provider:            "openai",
				ProviderDisplayName: "OpenAI",
				ModelConfigurations: []models.ModelConfiguration{
					{ID: intPtr(10), Name: "gpt-4o", IsVisible: true, DisplayName: strPtr("GPT-4o")},
					{ID: intPtr(11), Name: "gpt-4o-mini", IsVisible: false},
				},
			},
			{
				ID:                  2,
				Provider:            "anthropic",
				ProviderDisplayName: "Anthropic",
				ModelConfigurations: []models.ModelConfiguration{
					{ID: intPtr(20), Name: "claude-sonnet-5", IsVisible: true},
				},
			},
		},
		DefaultText: &models.DefaultModel{ProviderID: 2, ModelName: "claude-sonnet-5"},
	}
}

func TestFlattenModelOptions(t *testing.T) {
	options := flattenModelOptions(testProviderResponse())

	if len(options) != 2 {
		t.Fatalf("expected 2 visible models, got %d", len(options))
	}
	if options[0].label != "GPT-4o" {
		t.Errorf("label = %q, want %q", options[0].label, "GPT-4o")
	}
	if options[0].providerName != "OpenAI Prod" {
		t.Errorf("providerName = %q, want %q", options[0].providerName, "OpenAI Prod")
	}
	if options[0].isDefault {
		t.Error("gpt-4o should not be the default")
	}
	if options[1].label != "claude-sonnet-5" {
		t.Errorf("label = %q, want %q", options[1].label, "claude-sonnet-5")
	}
	if !options[1].isDefault {
		t.Error("claude-sonnet-5 should be the default")
	}
}

func TestFlattenModelOptionsNil(t *testing.T) {
	if got := flattenModelOptions(nil); got != nil {
		t.Errorf("expected nil for nil response, got %v", got)
	}
}

func TestModelsLoadedSetsStatusToDefault(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	updated, _ := m.handleModelsLoaded(ModelsLoadedMsg{Response: testProviderResponse()})
	m = updated.(Model)

	if m.status.modelName != "claude-sonnet-5" {
		t.Errorf("status model = %q, want %q", m.status.modelName, "claude-sonnet-5")
	}
	if m.viewport.pickerActive {
		t.Error("startup load must not open the picker")
	}
}

func TestModelsLoadedShowsPicker(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	updated, _ := m.handleModelsLoaded(ModelsLoadedMsg{Response: testProviderResponse(), ShowPicker: true})
	m = updated.(Model)

	if !m.viewport.pickerActive {
		t.Fatal("expected picker to be active")
	}
	if m.viewport.pickerType != pickerModel {
		t.Errorf("pickerType = %d, want pickerModel", m.viewport.pickerType)
	}
	if len(m.viewport.pickerItems) != 2 {
		t.Fatalf("expected 2 picker items, got %d", len(m.viewport.pickerItems))
	}
}

func TestStartupLoadKeepsOpenPickerListStable(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	updated, _ := m.handleModelsLoaded(ModelsLoadedMsg{Response: testProviderResponse(), ShowPicker: true})
	m = updated.(Model)

	late := &models.LLMProviderResponse{
		Providers: []models.LLMProviderDescriptor{
			{
				ID:                  3,
				Provider:            "ollama",
				ProviderDisplayName: "Ollama",
				ModelConfigurations: []models.ModelConfiguration{
					{ID: intPtr(30), Name: "llama3", IsVisible: true},
				},
			},
		},
	}
	updated, _ = m.handleModelsLoaded(ModelsLoadedMsg{Response: late})
	m = updated.(Model)

	if len(m.llmModels) != 2 {
		t.Errorf("expected the picker's model list to stay at 2 entries, got %d", len(m.llmModels))
	}
}

func TestSelectModelSetsOverrideAndStatus(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	updated, _ := m.handleModelsLoaded(ModelsLoadedMsg{Response: testProviderResponse()})
	m = updated.(Model)

	m, _ = cmdSelectModel(m, "0")

	if m.modelOverride == nil {
		t.Fatal("expected an override to be set")
	}
	if m.modelOverride.ModelConfigurationID == nil || *m.modelOverride.ModelConfigurationID != 10 {
		t.Errorf("ModelConfigurationID = %v, want 10", m.modelOverride.ModelConfigurationID)
	}
	if m.modelOverride.ModelVersion == nil || *m.modelOverride.ModelVersion != "gpt-4o" {
		t.Errorf("ModelVersion = %v, want gpt-4o", m.modelOverride.ModelVersion)
	}
	if m.status.modelName != "GPT-4o" {
		t.Errorf("status model = %q, want %q", m.status.modelName, "GPT-4o")
	}
}

func TestPickerBorderLinesShareOneWidth(t *testing.T) {
	v := newViewport(120, false)
	v.showPicker(pickerModel, []pickerItem{
		{id: "0", label: "Gemma 4 E2B *", detail: "Ollama"},
		{id: "1", label: "Qwen 3 8B", detail: "Ollama"},
	})

	var widths []int
	for _, line := range strings.Split(v.renderPicker(120, 30), "\n") {
		trimmed := strings.TrimRight(line, " ")
		if strings.TrimSpace(stripANSI(trimmed)) == "" {
			continue
		}
		widths = append(widths, lipgloss.Width(trimmed))
	}
	if len(widths) == 0 {
		t.Fatal("expected rendered panel lines")
	}
	for i, w := range widths {
		if w != widths[0] {
			t.Errorf("panel line %d width = %d, want %d (title border must match the panel)", i, w, widths[0])
		}
	}
}

func TestFormatPickerLabelAlignsDetail(t *testing.T) {
	rows := []pickerItem{
		{label: "Gemma 4 E2B *", detail: "Ollama"},
		{label: "Qwen 3 8B", detail: "Ollama"},
		{label: "GPT-4o", detail: "OpenAI"},
	}
	const avail = 40
	col := pickerDetailCol(rows, avail)
	if want := len([]rune("Gemma 4 E2B *")) + 2; col != want {
		t.Errorf("detailCol = %d, want %d (widest label + 2)", col, want)
	}
	for _, row := range rows {
		got := formatPickerLabel(row, avail, col)
		if idx := strings.Index(got, row.detail); idx != col {
			t.Errorf("%q: detail starts at %d, want column %d", got, idx, col)
		}
	}

	// A long label truncates so its detail stays on the shared column.
	longRow := pickerItem{label: strings.Repeat("x", 60), detail: "Ollama"}
	col = pickerDetailCol(append(rows[:len(rows):len(rows)], longRow), avail)
	got := formatPickerLabel(longRow, avail, col)
	if len([]rune(got)) > avail {
		t.Errorf("long label: width = %d, want <= %d", len([]rune(got)), avail)
	}
	if !strings.Contains(got, "...") || strings.Index(got, "Ollama") != col {
		t.Errorf("long label must truncate and keep detail on column %d, got %q", col, got)
	}
}

func TestSelectModelInvalidIndex(t *testing.T) {
	m := NewModel(config.DefaultConfig(), nil)
	m, _ = cmdSelectModel(m, "5")
	if m.modelOverride != nil {
		t.Error("expected no override for an out-of-range index")
	}
}
