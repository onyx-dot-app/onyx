package client

import (
	"context"
	"fmt"
	"net/http"
)

// FederatedConnectorConfig mirrors the write-side federated connector entry.
type FederatedConnectorConfig struct {
	FederatedConnectorID int64          `json:"federated_connector_id"`
	Entities             map[string]any `json:"entities"`
}

// FederatedConnectorSummary is the read-side entry. Id is the federated
// connector's id, matching FederatedConnectorID on the write side.
type FederatedConnectorSummary struct {
	ID       int64          `json:"id"`
	Name     string         `json:"name"`
	Source   string         `json:"source"`
	Entities map[string]any `json:"entities"`
}

// DocumentSetCreate mirrors DocumentSetCreationRequest.
type DocumentSetCreate struct {
	Name                string                     `json:"name"`
	Description         string                     `json:"description"`
	CCPairIDs           []int64                    `json:"cc_pair_ids"`
	IsPublic            bool                       `json:"is_public"`
	Users               []string                   `json:"users"`
	Groups              []int64                    `json:"groups"`
	FederatedConnectors []FederatedConnectorConfig `json:"federated_connectors"`
}

// DocumentSetUpdate mirrors DocumentSetUpdateRequest: a full replace that
// carries the id in the body rather than the path.
type DocumentSetUpdate struct {
	ID                  int64                      `json:"id"`
	Name                string                     `json:"name"`
	Description         string                     `json:"description"`
	CCPairIDs           []int64                    `json:"cc_pair_ids"`
	IsPublic            bool                       `json:"is_public"`
	Users               []string                   `json:"users"`
	Groups              []int64                    `json:"groups"`
	FederatedConnectors []FederatedConnectorConfig `json:"federated_connectors"`
}

// CCPairSummary is the cc-pair entry inside a document set.
type CCPairSummary struct {
	ID         int64  `json:"id"`
	Name       string `json:"name"`
	Source     string `json:"source"`
	AccessType string `json:"access_type"`
}

// DocumentSet mirrors DocumentSetSummary. Description is nullable on read but
// required on write, so an unset description round-trips as an empty string.
type DocumentSet struct {
	ID                          int64                       `json:"id"`
	Name                        string                      `json:"name"`
	Description                 *string                     `json:"description"`
	CCPairSummaries             []CCPairSummary             `json:"cc_pair_summaries"`
	IsUpToDate                  bool                        `json:"is_up_to_date"`
	IsPublic                    bool                        `json:"is_public"`
	Users                       []string                    `json:"users"`
	Groups                      []int64                     `json:"groups"`
	FederatedConnectorSummaries []FederatedConnectorSummary `json:"federated_connector_summaries"`
}

// CCPairIDs returns the ids of the cc-pairs in the set.
func (d *DocumentSet) CCPairIDs() []int64 {
	ids := make([]int64, 0, len(d.CCPairSummaries))
	for _, summary := range d.CCPairSummaries {
		ids = append(ids, summary.ID)
	}
	return ids
}

// CreateDocumentSet creates a document set and returns its id. The endpoint
// answers with a bare integer rather than an object.
func (c *Client) CreateDocumentSet(ctx context.Context, req DocumentSetCreate) (int64, error) {
	var id int64
	if err := c.doJSON(ctx, http.MethodPost, "/manage/admin/document-set", req, &id); err != nil {
		return 0, err
	}
	return id, nil
}

// GetDocumentSet reads one document set. A missing set answers 404.
func (c *Client) GetDocumentSet(ctx context.Context, id int64) (*DocumentSet, error) {
	var set DocumentSet
	path := fmt.Sprintf("/manage/admin/document-set/%d", id)
	if err := c.doJSON(ctx, http.MethodGet, path, nil, &set); err != nil {
		return nil, err
	}
	return &set, nil
}

// UpdateDocumentSet full-replaces a document set.
//
// Not replayable, though it is a PATCH: a committed write leaves the set
// syncing, and Onyx rejects a change to a syncing set. A replay would report
// failure for a change that already landed.
func (c *Client) UpdateDocumentSet(ctx context.Context, req DocumentSetUpdate) error {
	return c.doJSON(nonReplayable(ctx), http.MethodPatch, "/manage/admin/document-set", req, nil)
}

// DeleteDocumentSet marks a document set for deletion. The row survives until
// the background sync clears it, so callers poll GetDocumentSet until 404.
//
// Not replayable for the same reason as the update: this DELETE is not
// idempotent, because it leaves the set syncing and Onyx then rejects a second
// delete.
func (c *Client) DeleteDocumentSet(ctx context.Context, id int64) error {
	path := fmt.Sprintf("/manage/admin/document-set/%d", id)
	return c.doJSON(nonReplayable(ctx), http.MethodDelete, path, nil, nil)
}
