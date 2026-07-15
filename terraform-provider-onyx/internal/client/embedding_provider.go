package client

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
)

// CloudEmbeddingProvider mirrors both CloudEmbeddingProvider and
// CloudEmbeddingProviderCreationRequest (backend/onyx/server/manage/embedding/models.py),
// which have identical fields. Keyed by provider_type (there is no numeric id).
//
// APIKey in GET responses is MASKED, and unlike the LLM-provider upsert there
// is no api_key_changed flag: the backend overwrites every stored field with
// the request body verbatim. A masked value written back would permanently
// corrupt the stored key, so callers must never feed a GET response's APIKey
// into UpsertEmbeddingProvider.
type CloudEmbeddingProvider struct {
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

// GetEmbeddingProvider finds a provider by provider_type. The API has no
// get-by-id endpoint, so this scans the list; a missing provider returns an
// *APIError with 404.
func (c *Client) GetEmbeddingProvider(ctx context.Context, providerType string) (*CloudEmbeddingProvider, error) {
	providers, err := c.ListEmbeddingProviders(ctx)
	if err != nil {
		return nil, err
	}
	for i := range providers {
		if providers[i].ProviderType == providerType {
			return &providers[i], nil
		}
	}
	return nil, &APIError{
		StatusCode: http.StatusNotFound,
		ErrorCode:  "NOT_FOUND",
		Detail:     fmt.Sprintf("embedding provider %q not found", providerType),
	}
}

// DeleteEmbeddingProvider deletes the provider for a provider_type. The
// backend unconditionally refuses to delete the currently-active provider.
func (c *Client) DeleteEmbeddingProvider(ctx context.Context, providerType string) error {
	path := "/admin/embedding/embedding-provider/" + url.PathEscape(providerType)
	return c.doJSON(ctx, http.MethodDelete, path, nil, nil)
}
