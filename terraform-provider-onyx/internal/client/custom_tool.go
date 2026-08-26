package client

import (
	"context"
	"fmt"
	"net/http"
)

// Header is one header the action sends with every call it makes.
type Header struct {
	Key   string `json:"key"`
	Value string `json:"value"`
}

// CustomToolWrite mirrors CustomToolCreate and CustomToolUpdate, which carry
// the same fields. On update every field is nullable server-side, where null
// means "leave unchanged" (backend/onyx/db/tools.py:252-268); the provider
// always sends a complete object, so an update is a full replace.
type CustomToolWrite struct {
	Name            string         `json:"name"`
	Description     string         `json:"description"`
	Definition      map[string]any `json:"definition"`
	CustomHeaders   []Header       `json:"custom_headers"`
	PassthroughAuth bool           `json:"passthrough_auth"`
	OAuthConfigID   *int64         `json:"oauth_config_id"`
}

// CustomTool mirrors ToolSnapshot.
//
// CustomHeaders come back in full, values included. The whole snapshot is
// therefore secret-bearing and the resource marks the attribute sensitive.
type CustomTool struct {
	ID              int64          `json:"id"`
	Name            string         `json:"name"`
	Description     string         `json:"description"`
	Definition      map[string]any `json:"definition"`
	DisplayName     string         `json:"display_name"`
	InCodeToolID    *string        `json:"in_code_tool_id"`
	CustomHeaders   []Header       `json:"custom_headers"`
	PassthroughAuth bool           `json:"passthrough_auth"`
	MCPServerID     *int64         `json:"mcp_server_id"`
	OAuthConfigID   *int64         `json:"oauth_config_id"`
	Enabled         bool           `json:"enabled"`
}

// MethodSpec is one operation the validate endpoint parsed out of a definition.
type MethodSpec struct {
	Name    string `json:"name"`
	RawName string `json:"raw_name"`
	Summary string `json:"summary"`
	Path    string `json:"path"`
	Method  string `json:"method"`
}

type validateToolRequest struct {
	Definition map[string]any `json:"definition"`
}

type validateToolResponse struct {
	Methods []MethodSpec `json:"methods"`
}

// normalizeHeaders replaces a nil slice with an empty one.
//
// The update path stores custom_headers only when the field is non-null, so a
// nil slice would serialize as null and silently keep the headers the action
// already had. An empty list clears them, which is what "no headers" means
// in the configuration.
func normalizeHeaders(headers []Header) []Header {
	if headers == nil {
		return []Header{}
	}
	return headers
}

// CreateCustomTool creates a custom tool and returns the stored object.
func (c *Client) CreateCustomTool(ctx context.Context, req CustomToolWrite) (*CustomTool, error) {
	req.CustomHeaders = normalizeHeaders(req.CustomHeaders)
	var tool CustomTool
	if err := c.doJSON(ctx, http.MethodPost, "/admin/tool/custom", req, &tool); err != nil {
		return nil, err
	}
	return &tool, nil
}

// GetCustomTool reads one tool; a missing tool answers 404.
func (c *Client) GetCustomTool(ctx context.Context, id int64) (*CustomTool, error) {
	var tool CustomTool
	if err := c.doJSON(ctx, http.MethodGet, fmt.Sprintf("/tool/%d", id), nil, &tool); err != nil {
		return nil, err
	}
	return &tool, nil
}

// UpdateCustomTool replaces the tool definition and returns the stored object.
func (c *Client) UpdateCustomTool(ctx context.Context, id int64, req CustomToolWrite) (*CustomTool, error) {
	req.CustomHeaders = normalizeHeaders(req.CustomHeaders)
	var tool CustomTool
	path := fmt.Sprintf("/admin/tool/custom/%d", id)
	if err := c.doJSON(ctx, http.MethodPut, path, req, &tool); err != nil {
		return nil, err
	}
	return &tool, nil
}

// DeleteCustomTool deletes a tool for good; there is no tombstone.
//
// A tool an agent still lists is deleted anyway, and it is dropped from that
// agent along with it.
func (c *Client) DeleteCustomTool(ctx context.Context, id int64) error {
	return c.doJSON(ctx, http.MethodDelete, fmt.Sprintf("/admin/tool/custom/%d", id), nil, nil)
}

// ValidateCustomToolDefinition parses an OpenAPI definition and returns the
// methods it exposes. It stores nothing, so the provider can call it while
// validating a configuration.
func (c *Client) ValidateCustomToolDefinition(ctx context.Context, definition map[string]any) ([]MethodSpec, error) {
	var resp validateToolResponse
	req := validateToolRequest{Definition: definition}
	if err := c.doJSON(ctx, http.MethodPost, "/admin/tool/custom/validate", req, &resp); err != nil {
		return nil, err
	}
	return resp.Methods, nil
}

type toolStatusUpdate struct {
	ToolIDs []int64 `json:"tool_ids"`
	Enabled bool    `json:"enabled"`
}

// SetCustomToolEnabled enables or disables a tool. A disabled tool stays
// configured but no agent may call it. This is its own endpoint: neither
// create nor update carries the flag.
func (c *Client) SetCustomToolEnabled(ctx context.Context, id int64, enabled bool) error {
	req := toolStatusUpdate{ToolIDs: []int64{id}, Enabled: enabled}
	return c.doJSON(ctx, http.MethodPatch, "/admin/tool/status", req, nil)
}

// ListTools returns every action the caller can see, built-in ones included.
func (c *Client) ListTools(ctx context.Context) ([]CustomTool, error) {
	var tools []CustomTool
	if err := c.doJSON(ctx, http.MethodGet, "/tool", nil, &tools); err != nil {
		return nil, err
	}
	return tools, nil
}
