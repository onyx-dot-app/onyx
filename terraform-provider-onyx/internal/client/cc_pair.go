package client

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
)

// The only two statuses a client may set. The rest are server-cycled
// (backend/onyx/db/enums.py).
const (
	CCPairStatusActive = "ACTIVE"
	CCPairStatusPaused = "PAUSED"
)

// CCPairCreate mirrors ConnectorCredentialPairMetadata. Onyx v4.8 has no
// route that updates access_type, auto_sync_options, groups or
// processing_mode after create. DataAccess (Onyx v5.0+) is sent only when set,
// and has its own update route (SetCCPairDataAccess).
type CCPairCreate struct {
	Name            string         `json:"name"`
	AccessType      string         `json:"access_type"`
	AutoSyncOptions map[string]any `json:"auto_sync_options"`
	Groups          []int64        `json:"groups"`
	DataAccess      *[]int64       `json:"data_access,omitempty"`
	ProcessingMode  string         `json:"processing_mode"`
}

// CCPair mirrors the parts of CCPairFullInfo the provider manages. Groups,
// AutoSyncOptions and ProcessingMode are returned since Onyx v4.8.
type CCPair struct {
	ID                     int64          `json:"id"`
	Name                   string         `json:"name"`
	Status                 string         `json:"status"`
	AccessType             string         `json:"access_type"`
	Connector              Connector      `json:"connector"`
	Credential             Credential     `json:"credential"`
	NumDocsIndexed         int64          `json:"num_docs_indexed"`
	LastIndexAttemptStatus *string        `json:"last_index_attempt_status"`
	DeletionFailureMessage *string        `json:"deletion_failure_message"`
	Indexing               bool           `json:"indexing"`
	Groups                 []int64        `json:"groups"`
	AutoSyncOptions        map[string]any `json:"auto_sync_options"`
	ProcessingMode         string         `json:"processing_mode"`
}

// ccPairIdentifier mirrors ConnectorCredentialPairIdentifier: the deletion
// endpoint addresses a pair by its two halves rather than by its own id.
type ccPairIdentifier struct {
	ConnectorID  int64 `json:"connector_id"`
	CredentialID int64 `json:"credential_id"`
}

type ccPairStatusUpdate struct {
	Status string `json:"status"`
}

// statusResponse mirrors StatusResponse[int]. Data is only a meaningful id
// when Success is true — the no-op branches return the connector id instead.
type statusResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
	Data    int64  `json:"data"`
}

// CreateCCPair associates a credential with a connector and returns the new
// cc-pair id.
//
// The endpoint answers 200 with success=false when the pair already exists,
// and puts the *connector* id in data — so an unchecked caller would store the
// wrong id. Treat that as an error instead.
func (c *Client) CreateCCPair(ctx context.Context, connectorID, credentialID int64, req CCPairCreate) (int64, error) {
	var resp statusResponse
	path := fmt.Sprintf("/manage/connector/%d/credential/%d", connectorID, credentialID)
	if err := c.doJSON(nonReplayable(ctx), http.MethodPut, path, req, &resp); err != nil {
		return 0, err
	}
	if !resp.Success {
		return 0, fmt.Errorf("connector %d and credential %d were not associated: %s",
			connectorID, credentialID, resp.Message)
	}
	return resp.Data, nil
}

// GetCCPair reads one cc-pair. A missing pair answers 404.
func (c *Client) GetCCPair(ctx context.Context, id int64) (*CCPair, error) {
	var pair CCPair
	if err := c.doJSON(ctx, http.MethodGet, fmt.Sprintf("/manage/admin/cc-pair/%d", id), nil, &pair); err != nil {
		return nil, err
	}
	return &pair, nil
}

// SetCCPairName renames a cc-pair. The name is a query parameter, not a body.
func (c *Client) SetCCPairName(ctx context.Context, id int64, name string) error {
	path := fmt.Sprintf("/manage/admin/cc-pair/%d/name?new_name=%s", id, url.QueryEscape(name))
	return c.doJSON(ctx, http.MethodPut, path, nil, nil)
}

// SetCCPairStatus pauses or resumes a cc-pair. The endpoint rejects every
// status other than ACTIVE and PAUSED.
func (c *Client) SetCCPairStatus(ctx context.Context, id int64, status string) error {
	path := fmt.Sprintf("/manage/admin/cc-pair/%d/status", id)
	return c.doJSON(ctx, http.MethodPut, path, ccPairStatusUpdate{Status: status}, nil)
}

type ccPairDataAccess struct {
	Groups []UserGroupNamedRef `json:"groups"`
}

type ccPairDataAccessUpdate struct {
	GroupIDs []int64 `json:"group_ids"`
}

func (d ccPairDataAccess) groupIDs() []int64 {
	ids := make([]int64, 0, len(d.Groups))
	for _, group := range d.Groups {
		ids = append(ids, group.ID)
	}
	return ids
}

// GetCCPairDataAccess returns the groups whose members may read a private or
// sync_restricted pair, limited to the groups the caller can see. Enterprise
// Edition, Onyx v5.0+: older servers and Community Edition answer 404.
func (c *Client) GetCCPairDataAccess(ctx context.Context, id int64) ([]int64, error) {
	var resp ccPairDataAccess
	path := fmt.Sprintf("/manage/admin/cc-pair/%d/data-access", id)
	if err := c.doJSON(ctx, http.MethodGet, path, nil, &resp); err != nil {
		return nil, err
	}
	return resp.groupIDs(), nil
}

// SetCCPairDataAccess replaces the data-access groups and returns the stored
// set. Onyx keeps current groups the caller cannot see.
func (c *Client) SetCCPairDataAccess(ctx context.Context, id int64, groupIDs []int64) ([]int64, error) {
	if groupIDs == nil {
		groupIDs = []int64{}
	}
	var resp ccPairDataAccess
	path := fmt.Sprintf("/manage/admin/cc-pair/%d/data-access", id)
	if err := c.doJSON(ctx, http.MethodPut, path, ccPairDataAccessUpdate{GroupIDs: groupIDs}, &resp); err != nil {
		return nil, err
	}
	return resp.groupIDs(), nil
}

// DeleteCCPair schedules deletion of a cc-pair and the documents it indexed.
//
// This only marks the pair DELETING and wakes Celery; the row survives until
// the background task finishes. Callers poll GetCCPair until it answers 404.
// The synchronous DELETE on the association route is deliberately not used:
// it drops the pair while leaving its documents in the index.
func (c *Client) DeleteCCPair(ctx context.Context, connectorID, credentialID int64) error {
	body := ccPairIdentifier{ConnectorID: connectorID, CredentialID: credentialID}
	return c.doJSON(ctx, http.MethodPost, "/manage/admin/deletion-attempt", body, nil)
}
