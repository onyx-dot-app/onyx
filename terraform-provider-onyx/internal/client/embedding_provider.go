package client

import (
	"context"
	"net/http"
	"net/url"
)

// CloudEmbeddingProvider mirrors the backend models, keyed by provider_type.
// GET masks APIKey, so a GET-derived APIKey must never be written back.
// APIKeyChanged is request-only: unset, the server guesses from the mask.
type CloudEmbeddingProvider struct {
	APIKeyChanged  *bool   `json:"api_key_changed,omitempty"`
	ProviderType   string  `json:"provider_type"`
	APIKey         *string `json:"api_key"`
	APIURL         *string `json:"api_url"`
	APIVersion     *string `json:"api_version"`
	DeploymentName *string `json:"deployment_name"`
}

// UpsertEmbeddingProvider creates or updates the embedding provider for
// req.ProviderType (the PUT upserts by provider_type).
func (c *Client) UpsertEmbeddingProvider(ctx context.Context, req CloudEmbeddingProvider) (*CloudEmbeddingProvider, error) {
	var out CloudEmbeddingProvider
	if err := c.doJSON(ctx, http.MethodPut, "/admin/embedding/embedding-provider", req, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// ListEmbeddingProviders returns all configured cloud embedding providers.
func (c *Client) ListEmbeddingProviders(ctx context.Context) ([]CloudEmbeddingProvider, error) {
	var providers []CloudEmbeddingProvider
	if err := c.doJSON(ctx, http.MethodGet, "/admin/embedding/embedding-provider", nil, &providers); err != nil {
		return nil, err
	}
	return providers, nil
}

// GetEmbeddingProvider reads the provider for a provider_type. A provider
// that is not configured answers 404.
func (c *Client) GetEmbeddingProvider(ctx context.Context, providerType string) (*CloudEmbeddingProvider, error) {
	var provider CloudEmbeddingProvider
	path := "/admin/embedding/embedding-provider/" + url.PathEscape(providerType)
	if err := c.doJSON(ctx, http.MethodGet, path, nil, &provider); err != nil {
		return nil, err
	}
	return &provider, nil
}

// DeleteEmbeddingProvider deletes the provider for a provider_type. The
// backend unconditionally refuses to delete the currently-active provider.
func (c *Client) DeleteEmbeddingProvider(ctx context.Context, providerType string) error {
	path := "/admin/embedding/embedding-provider/" + url.PathEscape(providerType)
	return c.doJSON(ctx, http.MethodDelete, path, nil, nil)
}
