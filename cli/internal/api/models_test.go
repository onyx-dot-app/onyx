package api_test

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

const providersJSON = `{
	"providers": [
		{
			"id": 1,
			"name": "OpenAI",
			"provider": "openai",
			"provider_display_name": "OpenAI",
			"model_configurations": [
				{"id": 10, "name": "gpt-4o", "is_visible": true, "display_name": "GPT-4o"},
				{"id": 11, "name": "gpt-hidden", "is_visible": false, "display_name": null}
			]
		},
		{
			"id": 2,
			"name": "Anthropic",
			"provider": "anthropic",
			"provider_display_name": "Claude (Anthropic)",
			"model_configurations": [
				{"id": 20, "name": "claude-opus-5", "is_visible": true, "display_name": null}
			]
		}
	],
	"default_text": {"provider_id": 2, "model_name": "claude-opus-5"}
}`

func TestListModels_FlattensVisibleModels(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/llm/persona/3/providers" {
			t.Errorf("path = %s, want /api/llm/persona/3/providers", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(providersJSON))
	}))
	defer srv.Close()

	options, err := testutil.NewClient(srv.URL).ListModels(t.Context(), 3)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(options) != 2 {
		t.Fatalf("got %d models, want 2 (the hidden one must be dropped)", len(options))
	}

	first := options[0]
	if first.ConfigurationID != 10 || first.ModelName != "gpt-4o" || first.Label() != "GPT-4o" {
		t.Errorf("first = %+v, want the visible OpenAI model", first)
	}
	if first.Provider != "OpenAI" || first.ProviderLabel != "OpenAI" {
		t.Errorf("first provider = %q/%q", first.Provider, first.ProviderLabel)
	}
	if first.IsAgentDefault {
		t.Error("gpt-4o must not be marked the agent default")
	}

	second := options[1]
	if !second.IsAgentDefault {
		t.Error("claude-opus-5 must be marked the agent default")
	}
	// No display_name, so the label falls back to the model name.
	if second.Label() != "claude-opus-5" {
		t.Errorf("second label = %q, want claude-opus-5", second.Label())
	}
}

func TestSendMessageStream_SendsLLMOverride(t *testing.T) {
	bodies := make(chan []byte, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		bodies <- body
		w.Header().Set("Content-Type", "application/x-ndjson")
	}))
	defer srv.Close()

	selected := &models.SelectedModel{ConfigurationID: 10, Provider: "OpenAI", ModelName: "gpt-4o"}
	parentID := -1
	ch := testutil.NewClient(srv.URL).SendMessageStream(
		t.Context(), "hi", nil, 3, &parentID, nil, selected.Override(),
	)
	for range ch { //nolint:revive // drain the stream so the request completes
	}

	var payload models.SendMessagePayload
	if err := json.Unmarshal(<-bodies, &payload); err != nil {
		t.Fatalf("unmarshal request body: %v", err)
	}
	if payload.LLMOverride == nil {
		t.Fatal("llm_override missing from the request")
	}
	if payload.LLMOverride.ModelConfigurationID == nil || *payload.LLMOverride.ModelConfigurationID != 10 {
		t.Errorf("model_configuration_id = %v, want 10", payload.LLMOverride.ModelConfigurationID)
	}
	if payload.LLMOverride.ModelVersion != "gpt-4o" {
		t.Errorf("model_version = %q, want gpt-4o", payload.LLMOverride.ModelVersion)
	}
}

func TestSendMessageStream_OmitsOverrideWithoutSelection(t *testing.T) {
	bodies := make(chan []byte, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		bodies <- body
		w.Header().Set("Content-Type", "application/x-ndjson")
	}))
	defer srv.Close()

	var selected *models.SelectedModel
	parentID := -1
	ch := testutil.NewClient(srv.URL).SendMessageStream(
		t.Context(), "hi", nil, 3, &parentID, nil, selected.Override(),
	)
	for range ch { //nolint:revive // drain the stream so the request completes
	}

	var raw map[string]any
	if err := json.Unmarshal(<-bodies, &raw); err != nil {
		t.Fatalf("unmarshal request body: %v", err)
	}
	if _, present := raw["llm_override"]; present {
		t.Error("llm_override must be absent when no model is selected")
	}
}
