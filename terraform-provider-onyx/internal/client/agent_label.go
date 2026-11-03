package client

import (
	"context"
	"fmt"
	"net/http"
)

// AgentLabel mirrors PersonaLabelResponse. The wire paths still say persona.
type AgentLabel struct {
	Name string `json:"name"`
	ID   int64  `json:"id"`
}

type agentLabelCreate struct {
	Name string `json:"name"`
}

type agentLabelRename struct {
	LabelName string `json:"label_name"`
}

// ListAgentLabels returns every agent label.
func (c *Client) ListAgentLabels(ctx context.Context) ([]AgentLabel, error) {
	var labels []AgentLabel
	if err := c.doJSON(ctx, http.MethodGet, "/persona/labels", nil, &labels); err != nil {
		return nil, err
	}
	return labels, nil
}

// CreateAgentLabel creates a label. Names are unique.
func (c *Client) CreateAgentLabel(ctx context.Context, name string) (*AgentLabel, error) {
	var out AgentLabel
	if err := c.doJSON(ctx, http.MethodPost, "/persona/labels", agentLabelCreate{Name: name}, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// GetAgentLabel scans the list (no get-by-id endpoint); a missing label
// returns a synthetic 404 *APIError.
func (c *Client) GetAgentLabel(ctx context.Context, id int64) (*AgentLabel, error) {
	labels, err := c.ListAgentLabels(ctx)
	if err != nil {
		return nil, err
	}
	for i := range labels {
		if labels[i].ID == id {
			return &labels[i], nil
		}
	}
	return nil, &APIError{
		StatusCode: http.StatusNotFound,
		ErrorCode:  "NOT_FOUND",
		Detail:     fmt.Sprintf("agent label %d not found", id),
	}
}

// RenameAgentLabel changes a label's name.
func (c *Client) RenameAgentLabel(ctx context.Context, id int64, name string) error {
	path := fmt.Sprintf("/admin/persona/label/%d", id)
	return c.doJSON(ctx, http.MethodPatch, path, agentLabelRename{LabelName: name}, nil)
}

// DeleteAgentLabel deletes a label and detaches it from every agent. Deleting
// a missing label succeeds.
func (c *Client) DeleteAgentLabel(ctx context.Context, id int64) error {
	path := fmt.Sprintf("/admin/persona/label/%d", id)
	return c.doJSON(ctx, http.MethodDelete, path, nil, nil)
}
