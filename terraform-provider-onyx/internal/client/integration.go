package client

import (
	"context"
	"fmt"
	"net/http"
)

// Integration shapes the provider manages.
const (
	IntegrationShapeMCPServer = "mcp_server"
	IntegrationShapeOpenAPI   = "openapi"
)

// IntegrationConfig mirrors the config union of IntegrationCreate and
// AdminIntegrationDetail. Shape selects which of the other fields apply.
type IntegrationConfig struct {
	Shape           string  `json:"shape"`
	ServerURL       *string `json:"server_url,omitempty"`
	Transport       *string `json:"transport,omitempty"`
	OpenAPIDocument *string `json:"openapi_document,omitempty"`
}

// IntegrationCreate mirrors IntegrationCreate.
type IntegrationCreate struct {
	ForOrganization bool              `json:"for_organization"`
	Name            string            `json:"name"`
	Description     *string           `json:"description"`
	AuthMode        string            `json:"auth_mode"`
	AuthMethod      *string           `json:"auth_method"`
	HeaderTemplate  map[string]string `json:"header_template,omitempty"`
	Config          IntegrationConfig `json:"config"`
}

// IntegrationUpdate mirrors IntegrationUpdate. Onyx changes only the fields
// that are sent, so every field here is always sent: the provider applies the
// whole configuration on each update.
type IntegrationUpdate struct {
	Name           string            `json:"name"`
	Description    *string           `json:"description"`
	AuthMode       string            `json:"auth_mode"`
	AuthMethod     *string           `json:"auth_method"`
	HeaderTemplate map[string]string `json:"header_template"`
	Config         IntegrationConfig `json:"config"`
}

// IntegrationStatus is the state of a connection, such as "connected".
type IntegrationStatus struct {
	Reason *string `json:"reason"`
	State  string  `json:"state"`
}

// Integration mirrors the fields of AdminIntegrationDetail the provider reads.
type Integration struct {
	HeaderTemplate     map[string]string  `json:"header_template"`
	OrganizationStatus *IntegrationStatus `json:"organization_status"`
	Description        *string            `json:"description"`
	AuthMethod         *string            `json:"auth_method"`
	Config             IntegrationConfig  `json:"config"`
	Kind               string             `json:"kind"`
	Shape              string             `json:"shape"`
	Name               string             `json:"name"`
	AuthMode           string             `json:"auth_mode"`
	InstallationPolicy string             `json:"installation_policy"`
	ID                 int64              `json:"id"`
	Enabled            bool               `json:"enabled"`
}

type integrationInstallationPolicy struct {
	InstallationPolicy string `json:"installation_policy"`
}

type connectionFields struct {
	Fields map[string]string `json:"fields"`
}

// CreateIntegration creates an integration and returns the stored object.
func (c *Client) CreateIntegration(ctx context.Context, req IntegrationCreate) (*Integration, error) {
	var integration Integration
	if err := c.doJSON(ctx, http.MethodPost, "/admin/integrations", req, &integration); err != nil {
		return nil, err
	}
	return &integration, nil
}

// GetIntegration reads one integration; a missing one answers 404.
func (c *Client) GetIntegration(ctx context.Context, id int64) (*Integration, error) {
	var integration Integration
	if err := c.doJSON(ctx, http.MethodGet, fmt.Sprintf("/admin/integrations/%d", id), nil, &integration); err != nil {
		return nil, err
	}
	return &integration, nil
}

// UpdateIntegration applies an update and returns the stored object.
func (c *Client) UpdateIntegration(ctx context.Context, id int64, req IntegrationUpdate) (*Integration, error) {
	if req.HeaderTemplate == nil {
		req.HeaderTemplate = map[string]string{}
	}
	var integration Integration
	if err := c.doJSON(ctx, http.MethodPatch, fmt.Sprintf("/admin/integrations/%d", id), req, &integration); err != nil {
		return nil, err
	}
	return &integration, nil
}

// UpdateIntegrationEnabled turns the integration on or off for every user.
func (c *Client) UpdateIntegrationEnabled(ctx context.Context, id int64, enabled bool) (*Integration, error) {
	var integration Integration
	body := map[string]bool{"enabled": enabled}
	if err := c.doJSON(ctx, http.MethodPatch, fmt.Sprintf("/admin/integrations/%d", id), body, &integration); err != nil {
		return nil, err
	}
	return &integration, nil
}

// SetIntegrationInstallationPolicy sets the company install setting. Setting
// AVAILABLE on a private integration publishes it to the organization.
func (c *Client) SetIntegrationInstallationPolicy(ctx context.Context, id int64, policy string) error {
	path := fmt.Sprintf("/admin/integrations/%d/installation-policy", id)
	return c.doJSON(ctx, http.MethodPut, path, integrationInstallationPolicy{InstallationPolicy: policy}, nil)
}

// SaveIntegrationOrganizationConnection stores the connection fields of the
// organization, such as a shared API key.
func (c *Client) SaveIntegrationOrganizationConnection(ctx context.Context, id int64, fields map[string]string) error {
	path := fmt.Sprintf("/admin/integrations/%d/organization-connection", id)
	return c.doJSON(ctx, http.MethodPut, path, connectionFields{Fields: fields}, nil)
}

// RefreshIntegrationActions asks the integration's server for its tools and
// syncs the actions.
func (c *Client) RefreshIntegrationActions(ctx context.Context, id int64) error {
	path := fmt.Sprintf("/admin/integrations/%d/actions/refresh", id)
	return c.doJSON(ctx, http.MethodPost, path, nil, nil)
}

// DeleteIntegration deletes an integration and its actions.
func (c *Client) DeleteIntegration(ctx context.Context, id int64) error {
	return c.doJSON(ctx, http.MethodDelete, fmt.Sprintf("/admin/integrations/%d", id), nil, nil)
}
