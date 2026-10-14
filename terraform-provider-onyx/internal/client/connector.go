package client

import (
	"context"
	"fmt"
	"net/http"
)

// ConnectorUpsert mirrors ConnectorUpdateRequest. AccessType and Groups are
// validated on write but stored on the cc-pair, not on the connector.
type ConnectorUpsert struct {
	Name                    string         `json:"name"`
	Source                  string         `json:"source"`
	InputType               string         `json:"input_type"`
	ConnectorSpecificConfig map[string]any `json:"connector_specific_config"`
	RefreshFreq             *int64         `json:"refresh_freq"`
	PruneFreq               *int64         `json:"prune_freq"`
	IndexingStart           *string        `json:"indexing_start"`
	AccessType              string         `json:"access_type"`
	Groups                  []int64        `json:"groups"`
}

// Connector mirrors ConnectorSnapshot.
type Connector struct {
	ID                      int64          `json:"id"`
	Name                    string         `json:"name"`
	Source                  string         `json:"source"`
	InputType               string         `json:"input_type"`
	ConnectorSpecificConfig map[string]any `json:"connector_specific_config"`
	RefreshFreq             *int64         `json:"refresh_freq"`
	PruneFreq               *int64         `json:"prune_freq"`
	IndexingStart           *string        `json:"indexing_start"`
	CredentialIDs           []int64        `json:"credential_ids"`
}

// CreateConnector creates a connector and returns its id.
func (c *Client) CreateConnector(ctx context.Context, req ConnectorUpsert) (int64, error) {
	var created objectCreationIDResponse
	if err := c.doJSON(ctx, http.MethodPost, "/manage/admin/connector", req, &created); err != nil {
		return 0, err
	}
	return created.ID, nil
}

// ListConnectors returns every connector.
func (c *Client) ListConnectors(ctx context.Context) ([]Connector, error) {
	var connectors []Connector
	if err := c.doJSON(ctx, http.MethodGet, "/manage/connector", nil, &connectors); err != nil {
		return nil, err
	}
	return connectors, nil
}

// GetConnector reads one connector; a missing connector answers 404.
func (c *Client) GetConnector(ctx context.Context, id int64) (*Connector, error) {
	var connector Connector
	if err := c.doJSON(ctx, http.MethodGet, fmt.Sprintf("/manage/connector/%d", id), nil, &connector); err != nil {
		return nil, err
	}
	return &connector, nil
}

// UpdateConnector replaces the connector definition and returns the result.
// The server rewrites an omitted prune_freq to its default, so callers read
// the returned snapshot rather than assuming the request body was stored.
func (c *Client) UpdateConnector(ctx context.Context, id int64, req ConnectorUpsert) (*Connector, error) {
	var connector Connector
	path := fmt.Sprintf("/manage/admin/connector/%d", id)
	if err := c.doJSON(ctx, http.MethodPatch, path, req, &connector); err != nil {
		return nil, err
	}
	return &connector, nil
}

// DeleteConnector deletes a connector. Deleting a connector that is already
// gone succeeds; one still attached to a cc-pair fails.
func (c *Client) DeleteConnector(ctx context.Context, id int64) error {
	return c.doJSON(ctx, http.MethodDelete, fmt.Sprintf("/manage/admin/connector/%d", id), nil, nil)
}
