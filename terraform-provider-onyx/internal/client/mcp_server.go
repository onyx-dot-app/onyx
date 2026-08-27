package client

import (
	"context"
	"fmt"
	"net/http"
)

// MCP authentication types. OAUTH and PT_OAUTH need an interactive browser
// round-trip, so the provider refuses them while validating a configuration.
const (
	MCPAuthNone     = "NONE"
	MCPAuthAPIToken = "API_TOKEN"
	MCPAuthOAuth    = "OAUTH"
	MCPAuthPTOAuth  = "PT_OAUTH"
)

// Who supplies the credentials an MCP server is called with.
const (
	MCPPerformerAdmin   = "ADMIN"
	MCPPerformerPerUser = "PER_USER"
)

// MCPAuthTemplate is the header set Onyx sends to the MCP server. Values may
// hold `{placeholder}` fields that each user fills in.
type MCPAuthTemplate struct {
	Headers map[string]string `json:"headers"`
	// Derived server-side from the placeholders in Headers; never sent.
	RequiredFields []string `json:"required_fields,omitempty"`
}

// MCPServerWrite mirrors MCPToolCreateRequest, the auth-configuring upsert.
// The same body creates and updates: ExistingServerID selects which.
//
// It does not carry available_in_craft, which only the PATCH endpoint accepts,
// so a fully specified server costs two calls.
type MCPServerWrite struct {
	ExistingServerID *int64 `json:"existing_server_id,omitempty"`
	Name             string `json:"name"`
	// Always sent. Omitting it preserves the stored value, so a description
	// cleared in the configuration has to go out as an empty string.
	Description   string `json:"description"`
	ServerURL     string `json:"server_url"`
	AuthType      string `json:"auth_type"`
	AuthPerformer string `json:"auth_performer"`
	Transport     string `json:"transport"`

	// APIToken is stored as admin_credentials["api_key"] and read back masked,
	// so it is never refreshed from the server. APITokenChanged tells Onyx to
	// take the value rather than keep the one it holds.
	APIToken        *string `json:"api_token,omitempty"`
	APITokenChanged bool    `json:"api_token_changed"`

	AuthTemplate            *MCPAuthTemplate  `json:"auth_template,omitempty"`
	AdminCredentials        map[string]string `json:"admin_credentials,omitempty"`
	AdminCredentialsChanged map[string]bool   `json:"admin_credentials_changed,omitempty"`

	// Null leaves the stored access unchanged. They stay pointers so a caller
	// can tell "no access list" (an empty list, which clears) apart from
	// "do not touch it" (null).
	IsPublic *bool     `json:"is_public,omitempty"`
	Groups   *[]int64  `json:"groups,omitempty"`
	Users    *[]string `json:"users,omitempty"`
}

// MCPServerPatch carries the one field of MCPServerSimpleUpdateRequest the
// upsert cannot reach. The request model holds more, and the endpoint also
// covers per-tool Craft policies, but Onyx rejects a policy for a tool it has
// never discovered, so nothing here would be able to set one.
type MCPServerPatch struct {
	AvailableInCraft *bool `json:"available_in_craft,omitempty"`
}

// MCPServer mirrors the MCPServer response model.
//
// Secrets are masked on the way out: an admin API token reads back as a run of
// bullet characters, so no field here is safe to write back into an upsert.
type MCPServer struct {
	ID          int64   `json:"id"`
	Name        string  `json:"name"`
	Description *string `json:"description"`
	ServerURL   string  `json:"server_url"`
	// Owner is the identity that configured the server. For an API-key run
	// that is the key's synthetic address, not a real mailbox.
	Owner            string           `json:"owner"`
	Transport        *string          `json:"transport"`
	AuthType         *string          `json:"auth_type"`
	AuthPerformer    *string          `json:"auth_performer"`
	Status           string           `json:"status"`
	IsPublic         bool             `json:"is_public"`
	Groups           []int64          `json:"groups"`
	Users            []string         `json:"users"`
	AvailableInCraft bool             `json:"available_in_craft"`
	LastRefreshedAt  *string          `json:"last_refreshed_at"`
	ToolCount        int64            `json:"tool_count"`
	AuthTemplate     *MCPAuthTemplate `json:"auth_template"`
}

type mcpServerCreateResponse struct {
	ServerID int64 `json:"server_id"`
}

// UpsertMCPServer creates an MCP server, or updates the one named by
// ExistingServerID, and returns its id.
//
// The response is a summary rather than the stored object, so callers that
// need the full record read it back.
func (c *Client) UpsertMCPServer(ctx context.Context, req MCPServerWrite) (int64, error) {
	var resp mcpServerCreateResponse
	if err := c.doJSON(ctx, http.MethodPost, "/admin/mcp/servers/create", req, &resp); err != nil {
		return 0, err
	}
	return resp.ServerID, nil
}

// PatchMCPServer applies the fields the upsert cannot reach and returns the
// stored object.
func (c *Client) PatchMCPServer(ctx context.Context, id int64, req MCPServerPatch) (*MCPServer, error) {
	var server MCPServer
	path := fmt.Sprintf("/admin/mcp/server/%d", id)
	if err := c.doJSON(ctx, http.MethodPatch, path, req, &server); err != nil {
		return nil, err
	}
	return &server, nil
}

// GetMCPServer reads one server; a missing server answers 404.
func (c *Client) GetMCPServer(ctx context.Context, id int64) (*MCPServer, error) {
	var server MCPServer
	path := fmt.Sprintf("/admin/mcp/servers/%d", id)
	if err := c.doJSON(ctx, http.MethodGet, path, nil, &server); err != nil {
		return nil, err
	}
	return &server, nil
}

// DeleteMCPServer deletes a server and everything hanging off it. The delete
// is real: the id answers 404 afterwards, and so does deleting it twice.
func (c *Client) DeleteMCPServer(ctx context.Context, id int64) error {
	return c.doJSON(ctx, http.MethodDelete, fmt.Sprintf("/admin/mcp/server/%d", id), nil, nil)
}
