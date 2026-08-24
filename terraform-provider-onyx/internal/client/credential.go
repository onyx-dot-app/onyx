package client

import (
	"context"
	"fmt"
	"net/http"
)

// CredentialUpsert mirrors CredentialBase (backend/onyx/server/documents/models.py).
type CredentialUpsert struct {
	CredentialJSON map[string]any `json:"credential_json"`
	AdminPublic    bool           `json:"admin_public"`
	Source         string         `json:"source"`
	Name           *string        `json:"name"`
	CuratorPublic  bool           `json:"curator_public"`
	Groups         []int64        `json:"groups"`
}

// Credential mirrors CredentialSnapshot. CredentialJSON always comes back
// masked, so it is never a source of truth for Terraform state.
type Credential struct {
	ID             int64          `json:"id"`
	CredentialJSON map[string]any `json:"credential_json"`
	AdminPublic    bool           `json:"admin_public"`
	Source         string         `json:"source"`
	Name           *string        `json:"name"`
	CuratorPublic  bool           `json:"curator_public"`
	UserID         *string        `json:"user_id"`
}

// credentialNameUpdate mirrors CredentialDataUpdateRequest.
type credentialNameUpdate struct {
	Name           string         `json:"name"`
	CredentialJSON map[string]any `json:"credential_json"`
}

type objectCreationIDResponse struct {
	ID int64 `json:"id"`
}

// CreateCredential creates a credential and returns its id.
func (c *Client) CreateCredential(ctx context.Context, req CredentialUpsert) (int64, error) {
	var created objectCreationIDResponse
	if err := c.doJSON(ctx, http.MethodPost, "/manage/credential", req, &created); err != nil {
		return 0, err
	}
	return created.ID, nil
}

// ListCredentials returns every credential the caller can see.
func (c *Client) ListCredentials(ctx context.Context) ([]Credential, error) {
	var credentials []Credential
	if err := c.doJSON(ctx, http.MethodGet, "/manage/admin/credential", nil, &credentials); err != nil {
		return nil, err
	}
	return credentials, nil
}

// GetCredential finds a credential by id. GET /manage/credential/{id} answers
// 401 for a missing credential, which is indistinguishable from a rejected
// key, so this scans the admin list instead and synthesizes a 404.
func (c *Client) GetCredential(ctx context.Context, id int64) (*Credential, error) {
	credentials, err := c.ListCredentials(ctx)
	if err != nil {
		return nil, err
	}
	for i := range credentials {
		if credentials[i].ID == id {
			return &credentials[i], nil
		}
	}
	return nil, &APIError{
		StatusCode: http.StatusNotFound,
		ErrorCode:  "NOT_FOUND",
		Detail:     fmt.Sprintf("credential with id %d not found", id),
	}
}

// ReplaceCredentialJSON replaces the stored secret payload. Only
// credential_json is applied; the endpoint ignores every other field.
func (c *Client) ReplaceCredentialJSON(ctx context.Context, id int64, req CredentialUpsert) error {
	return c.doJSON(ctx, http.MethodPatch, fmt.Sprintf("/manage/credential/%d", id), req, nil)
}

// SetCredentialName renames a credential. The endpoint also merges
// credentialJSON into the stored payload, so callers pass the full desired
// payload to keep the merge a no-op.
func (c *Client) SetCredentialName(ctx context.Context, id int64, name string, credentialJSON map[string]any) error {
	body := credentialNameUpdate{Name: name, CredentialJSON: credentialJSON}
	return c.doJSON(ctx, http.MethodPut, fmt.Sprintf("/manage/admin/credential/%d", id), body, nil)
}

// DeleteCredential deletes a credential. It fails while the credential is
// still attached to a connector.
func (c *Client) DeleteCredential(ctx context.Context, id int64) error {
	return c.doJSON(ctx, http.MethodDelete, fmt.Sprintf("/manage/admin/credential/%d", id), nil, nil)
}
