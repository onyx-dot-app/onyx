package client

import (
	"context"
	"fmt"
	"net/http"
)

// APIKeyArgs mirrors APIKeyArgs (backend/onyx/server/api_key/models.py).
type APIKeyArgs struct {
	Name *string `json:"name"`
	Role string  `json:"role"`
}

// APIKeyDescriptor mirrors ApiKeyDescriptor (backend/onyx/auth/api_key.py).
// APIKey (the plaintext credential) is only present in create/regenerate
// responses — list responses always return null.
type APIKeyDescriptor struct {
	APIKeyID      int64   `json:"api_key_id"`
	APIKeyDisplay string  `json:"api_key_display"`
	APIKey        *string `json:"api_key"`
	APIKeyName    *string `json:"api_key_name"`
	APIKeyRole    string  `json:"api_key_role"`
	UserID        string  `json:"user_id"`
}

// CreateAPIKey creates an API key. The response carries the plaintext key —
// the only time it is ever returned.
func (c *Client) CreateAPIKey(ctx context.Context, args APIKeyArgs) (*APIKeyDescriptor, error) {
	var desc APIKeyDescriptor
	if err := c.doJSON(ctx, http.MethodPost, "/admin/api-key", args, &desc); err != nil {
		return nil, err
	}
	return &desc, nil
}

// ListAPIKeys returns all API keys (without plaintext key material).
func (c *Client) ListAPIKeys(ctx context.Context) ([]APIKeyDescriptor, error) {
	var keys []APIKeyDescriptor
	if err := c.doJSON(ctx, http.MethodGet, "/admin/api-key", nil, &keys); err != nil {
		return nil, err
	}
	return keys, nil
}

// GetAPIKey finds an API key by id. The API has no get-by-id endpoint, so
// this scans the list; a missing key returns an *APIError with 404.
func (c *Client) GetAPIKey(ctx context.Context, id int64) (*APIKeyDescriptor, error) {
	keys, err := c.ListAPIKeys(ctx)
	if err != nil {
		return nil, err
	}
	for i := range keys {
		if keys[i].APIKeyID == id {
			return &keys[i], nil
		}
	}
	return nil, &APIError{
		StatusCode: http.StatusNotFound,
		ErrorCode:  "NOT_FOUND",
		Detail:     fmt.Sprintf("API key with id %d not found", id),
	}
}

// UpdateAPIKey updates an API key's name and role.
func (c *Client) UpdateAPIKey(ctx context.Context, id int64, args APIKeyArgs) (*APIKeyDescriptor, error) {
	var desc APIKeyDescriptor
	path := fmt.Sprintf("/admin/api-key/%d", id)
	if err := c.doJSON(ctx, http.MethodPatch, path, args, &desc); err != nil {
		return nil, err
	}
	return &desc, nil
}

// DeleteAPIKey deletes an API key.
func (c *Client) DeleteAPIKey(ctx context.Context, id int64) error {
	return c.doJSON(ctx, http.MethodDelete, fmt.Sprintf("/admin/api-key/%d", id), nil, nil)
}

// RegenerateAPIKey rotates the key material, returning the new plaintext key.
func (c *Client) RegenerateAPIKey(ctx context.Context, id int64) (*APIKeyDescriptor, error) {
	var desc APIKeyDescriptor
	path := fmt.Sprintf("/admin/api-key/%d/regenerate", id)
	if err := c.doJSON(ctx, http.MethodPost, path, nil, &desc); err != nil {
		return nil, err
	}
	return &desc, nil
}
