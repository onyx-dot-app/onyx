package client

import (
	"context"
	"net/http"
	"testing"
)

const llmProviderListJSON = `{
	"providers": [{
		"id": 3,
		"name": "openai-prod",
		"provider": "openai",
		"api_key": "sk-****1234",
		"api_base": null,
		"api_version": null,
		"custom_config": null,
		"is_public": true,
		"is_auto_mode": false,
		"groups": [],
		"personas": [],
		"deployment_name": null,
		"model_configurations": [{
			"id": 11,
			"name": "gpt-5-mini",
			"is_visible": true,
			"max_input_tokens": 272000,
			"supports_image_input": true,
			"supports_reasoning": true,
			"display_name": "GPT-5 Mini",
			"custom_display_name": null
		}]
	}],
	"default_text": {"provider_id": 3, "model_name": "gpt-5-mini"},
	"default_vision": null
}`

func TestUpsertLLMProviderCreate(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"id": 3, "provider": "openai", "model_configurations": []}`)
	req := LLMProviderUpsertRequest{
		Name:          strPtr("openai-prod"),
		Provider:      "openai",
		APIKey:        strPtr("sk-real-key"),
		IsPublic:      true,
		APIKeyChanged: true,
		ModelConfigurations: []ModelConfigurationUpsert{
			{Name: "gpt-5-mini", IsVisible: true},
		},
	}
	view, err := c.UpsertLLMProvider(context.Background(), req, true)
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPut || captured.Path != "/admin/llm/provider?is_creation=true" {
		t.Errorf("got %s %s, want PUT /admin/llm/provider?is_creation=true", captured.Method, captured.Path)
	}
	if view.ID != 3 {
		t.Errorf("unexpected view: %+v", view)
	}

	// The PUT is a full replace: every field must be present, and nil slices
	// must be normalized to [] (Pydantic list[int] rejects null).
	body := bodyAsMap(t, captured.Body)
	for _, field := range []string{
		"id", "name", "provider", "api_key", "api_base", "api_version",
		"custom_config", "is_public", "is_auto_mode", "groups", "personas",
		"deployment_name", "api_key_changed", "custom_config_changed",
		"model_configurations",
	} {
		if _, present := body[field]; !present {
			t.Errorf("field %q missing from upsert body: %s", field, captured.Body)
		}
	}
	if _, isArray := body["groups"].([]any); !isArray {
		t.Errorf("groups should serialize as [], got %v", body["groups"])
	}
	if _, isArray := body["personas"].([]any); !isArray {
		t.Errorf("personas should serialize as [], got %v", body["personas"])
	}
	if body["api_key_changed"] != true {
		t.Error("api_key_changed should be true")
	}

	modelConfigs := body["model_configurations"].([]any)
	mc := modelConfigs[0].(map[string]any)
	for _, field := range []string{
		"name", "is_visible", "max_input_tokens", "supports_image_input",
		"supports_reasoning", "display_name", "custom_display_name",
	} {
		if _, present := mc[field]; !present {
			t.Errorf("model_configurations field %q missing: %s", field, captured.Body)
		}
	}
}

func TestUpsertLLMProviderUpdate(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"id": 3, "provider": "openai", "model_configurations": []}`)
	id := int64(3)
	req := LLMProviderUpsertRequest{ID: &id, Provider: "openai"}
	if _, err := c.UpsertLLMProvider(context.Background(), req, false); err != nil {
		t.Fatal(err)
	}
	if captured.Path != "/admin/llm/provider?is_creation=false" {
		t.Errorf("got path %s, want /admin/llm/provider?is_creation=false", captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	if body["id"] != float64(3) {
		t.Errorf("id should be 3 in update body: %s", captured.Body)
	}
	if body["api_key_changed"] != false {
		t.Error("api_key_changed should default to false")
	}
}

func TestGetLLMProvider(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, llmProviderListJSON)
	view, err := c.GetLLMProvider(context.Background(), 3)
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodGet || captured.Path != "/admin/llm/provider" {
		t.Errorf("got %s %s, want GET /admin/llm/provider", captured.Method, captured.Path)
	}
	if view.Provider != "openai" || len(view.ModelConfigurations) != 1 {
		t.Errorf("unexpected view: %+v", view)
	}

	if _, err := c.GetLLMProvider(context.Background(), 999); !IsNotFound(err) {
		t.Errorf("missing id should return a 404 APIError, got %v", err)
	}
}

func TestListLLMProvidersDefaults(t *testing.T) {
	c, _ := newTestServer(t, http.StatusOK, llmProviderListJSON)
	list, err := c.ListLLMProviders(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if list.DefaultText == nil || list.DefaultText.ProviderID != 3 || list.DefaultText.ModelName != "gpt-5-mini" {
		t.Errorf("unexpected default_text: %+v", list.DefaultText)
	}
	if list.DefaultVision != nil {
		t.Errorf("default_vision should be nil, got %+v", list.DefaultVision)
	}
}

func TestDeleteLLMProvider(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.DeleteLLMProvider(context.Background(), 3, true); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodDelete || captured.Path != "/admin/llm/provider/3?force=true" {
		t.Errorf("got %s %s, want DELETE /admin/llm/provider/3?force=true", captured.Method, captured.Path)
	}
}

func TestSetDefaultLLMModel(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.SetDefaultLLMModel(context.Background(), DefaultModel{ProviderID: 3, ModelName: "gpt-5-mini"}); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPost || captured.Path != "/admin/llm/default" {
		t.Errorf("got %s %s, want POST /admin/llm/default", captured.Method, captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	if body["provider_id"] != float64(3) || body["model_name"] != "gpt-5-mini" {
		t.Errorf("unexpected body: %s", captured.Body)
	}
}

func TestSetDefaultVisionModel(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.SetDefaultVisionModel(context.Background(), DefaultModel{ProviderID: 3, ModelName: "gpt-5-mini"}); err != nil {
		t.Fatal(err)
	}
	if captured.Path != "/admin/llm/default-vision" {
		t.Errorf("got path %s, want /admin/llm/default-vision", captured.Path)
	}
}
