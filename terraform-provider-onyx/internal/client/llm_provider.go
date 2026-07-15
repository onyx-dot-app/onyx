package client

import (
	"context"
	"fmt"
	"net/http"
)

// ModelConfigurationUpsert mirrors ModelConfigurationUpsertRequest
// (backend/onyx/server/manage/llm/models.py).
type ModelConfigurationUpsert struct {
	Name               string  `json:"name"`
	IsVisible          bool    `json:"is_visible"`
	MaxInputTokens     *int64  `json:"max_input_tokens"`
	SupportsImageInput *bool   `json:"supports_image_input"`
	SupportsReasoning  *bool   `json:"supports_reasoning"`
	DisplayName        *string `json:"display_name"`
	CustomDisplayName  *string `json:"custom_display_name"`
}

// ModelConfigurationView mirrors ModelConfigurationView. Only fields the
// provider consumes are declared; extra response fields are ignored.
type ModelConfigurationView struct {
	ID                 *int64  `json:"id"`
	Name               string  `json:"name"`
	IsVisible          bool    `json:"is_visible"`
	MaxInputTokens     *int64  `json:"max_input_tokens"`
	SupportsImageInput bool    `json:"supports_image_input"`
	SupportsReasoning  bool    `json:"supports_reasoning"`
	DisplayName        *string `json:"display_name"`
	CustomDisplayName  *string `json:"custom_display_name"`
}

// LLMProviderUpsertRequest mirrors LLMProviderUpsertRequest. Fields are
// deliberately not omitempty: the PUT is a full replace, so the request must
// always assert the complete desired state.
type LLMProviderUpsertRequest struct {
	ID                  *int64                     `json:"id"`
	Name                *string                    `json:"name"`
	Provider            string                     `json:"provider"`
	APIKey              *string                    `json:"api_key"`
	APIBase             *string                    `json:"api_base"`
	APIVersion          *string                    `json:"api_version"`
	CustomConfig        map[string]string          `json:"custom_config"`
	IsPublic            bool                       `json:"is_public"`
	IsAutoMode          bool                       `json:"is_auto_mode"`
	Groups              []int64                    `json:"groups"`
	Personas            []int64                    `json:"personas"`
	DeploymentName      *string                    `json:"deployment_name"`
	APIKeyChanged       bool                       `json:"api_key_changed"`
	CustomConfigChanged bool                       `json:"custom_config_changed"`
	ModelConfigurations []ModelConfigurationUpsert `json:"model_configurations"`
}

// LLMProviderView mirrors LLMProviderView. api_key and custom_config values
// are MASKED in responses — they must never be written back to the API.
type LLMProviderView struct {
	ID                  int64                    `json:"id"`
	Name                *string                  `json:"name"`
	Provider            string                   `json:"provider"`
	APIKey              *string                  `json:"api_key"`
	APIBase             *string                  `json:"api_base"`
	APIVersion          *string                  `json:"api_version"`
	CustomConfig        map[string]string        `json:"custom_config"`
	IsPublic            bool                     `json:"is_public"`
	IsAutoMode          bool                     `json:"is_auto_mode"`
	Groups              []int64                  `json:"groups"`
	Personas            []int64                  `json:"personas"`
	DeploymentName      *string                  `json:"deployment_name"`
	ModelConfigurations []ModelConfigurationView `json:"model_configurations"`
}

// DefaultModel mirrors DefaultModel: the global default (provider, model) pair.
type DefaultModel struct {
	ProviderID int64  `json:"provider_id"`
	ModelName  string `json:"model_name"`
}

// LLMProviderList mirrors LLMProviderResponse[LLMProviderView].
type LLMProviderList struct {
	Providers     []LLMProviderView `json:"providers"`
	DefaultText   *DefaultModel     `json:"default_text"`
	DefaultVision *DefaultModel     `json:"default_vision"`
}

// UpsertLLMProvider creates (isCreation=true) or updates an LLM provider.
// Updates must carry the provider id in req.ID.
func (c *Client) UpsertLLMProvider(ctx context.Context, req LLMProviderUpsertRequest, isCreation bool) (*LLMProviderView, error) {
	if req.Groups == nil {
		req.Groups = []int64{}
	}
	if req.Personas == nil {
		req.Personas = []int64{}
	}
	if req.ModelConfigurations == nil {
		req.ModelConfigurations = []ModelConfigurationUpsert{}
	}
	var view LLMProviderView
	path := fmt.Sprintf("/admin/llm/provider?is_creation=%t", isCreation)
	if err := c.doJSON(ctx, http.MethodPut, path, req, &view); err != nil {
		return nil, err
	}
	return &view, nil
}

// ListLLMProviders returns all LLM providers plus the global default models.
func (c *Client) ListLLMProviders(ctx context.Context) (*LLMProviderList, error) {
	var list LLMProviderList
	if err := c.doJSON(ctx, http.MethodGet, "/admin/llm/provider", nil, &list); err != nil {
		return nil, err
	}
	return &list, nil
}

// GetLLMProvider finds a provider by id. The API has no get-by-id endpoint,
// so this scans the list; a missing provider returns an *APIError with 404.
func (c *Client) GetLLMProvider(ctx context.Context, id int64) (*LLMProviderView, error) {
	list, err := c.ListLLMProviders(ctx)
	if err != nil {
		return nil, err
	}
	for i := range list.Providers {
		if list.Providers[i].ID == id {
			return &list.Providers[i], nil
		}
	}
	return nil, &APIError{
		StatusCode: http.StatusNotFound,
		ErrorCode:  "NOT_FOUND",
		Detail:     fmt.Sprintf("LLM provider with id %d not found", id),
	}
}

// DeleteLLMProvider deletes a provider. force allows deleting the provider
// that currently holds the global default model.
func (c *Client) DeleteLLMProvider(ctx context.Context, id int64, force bool) error {
	path := fmt.Sprintf("/admin/llm/provider/%d?force=%t", id, force)
	return c.doJSON(ctx, http.MethodDelete, path, nil, nil)
}

// SetDefaultLLMModel sets the global default text model.
func (c *Client) SetDefaultLLMModel(ctx context.Context, req DefaultModel) error {
	return c.doJSON(ctx, http.MethodPost, "/admin/llm/default", req, nil)
}

// SetDefaultVisionModel sets the global default vision model.
func (c *Client) SetDefaultVisionModel(ctx context.Context, req DefaultModel) error {
	return c.doJSON(ctx, http.MethodPost, "/admin/llm/default-vision", req, nil)
}
