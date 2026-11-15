package client

import (
	"context"
	"fmt"
	"net/http"
)

// APIKeyArgs mirrors APIKeyArgs (backend/onyx/server/api_key/models.py).
type APIKeyArgs struct {
	Name     *string `json:"name"`
	GroupIDs []int64 `json:"group_ids"`
}

// normalized returns args safe to send: a nil GroupIDs marshals to JSON null,
// which the backend rejects with a 422 rather than reading as "no groups".
func (a APIKeyArgs) normalized() APIKeyArgs {
	if a.GroupIDs == nil {
		a.GroupIDs = []int64{}
	}
	return a
}

// UserGroupInfo mirrors UserGroupInfo (backend/onyx/server/models.py).
type UserGroupInfo struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
}

// APIKeyDescriptor mirrors the backend model; APIKey (plaintext) is set only on create/regenerate.
type APIKeyDescriptor struct {
	APIKeyID      int64           `json:"api_key_id"`
	APIKeyDisplay string          `json:"api_key_display"`
	APIKey        *string         `json:"api_key"`
	APIKeyName    *string         `json:"api_key_name"`
	Groups        []UserGroupInfo `json:"groups"`
	UserID        string          `json:"user_id"`
}

// CreateAPIKey creates an API key. The response carries the plaintext key —
// the only time it is ever returned.
func (c *Client) CreateAPIKey(ctx context.Context, args APIKeyArgs) (*APIKeyDescriptor, error) {
	var desc APIKeyDescriptor
	if err := c.doJSON(ctx, http.MethodPost, "/admin/api-key", args.normalized(), &desc); err != nil {
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

// UpdateAPIKey updates an API key's name and group membership.
func (c *Client) UpdateAPIKey(ctx context.Context, id int64, args APIKeyArgs) (*APIKeyDescriptor, error) {
	var desc APIKeyDescriptor
	path := fmt.Sprintf("/admin/api-key/%d", id)
	if err := c.doJSON(ctx, http.MethodPatch, path, args.normalized(), &desc); err != nil {
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
