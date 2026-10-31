package client

import (
	"context"
	"net/http"
	"testing"
)

// The create endpoint answers with a bare integer, not an object.
func TestCreateDocumentSetParsesBareInt(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `12`)
	id, err := c.CreateDocumentSet(context.Background(), DocumentSetCreate{
		Name:                "engineering",
		Description:         "",
		CCPairIDs:           []int64{1, 2},
		IsPublic:            true,
		Users:               []string{},
		Groups:              []int64{},
		FederatedConnectors: []FederatedConnectorConfig{},
	})
	if err != nil {
		t.Fatal(err)
	}
	if id != 12 {
		t.Errorf("id = %d, want 12", id)
	}
	if captured.Method != http.MethodPost || captured.Path != "/manage/admin/document-set" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	if body["name"] != "engineering" || body["is_public"] != true {
		t.Errorf("unexpected body: %v", body)
	}
	for _, field := range []string{"description", "cc_pair_ids", "users", "groups", "federated_connectors"} {
		if _, ok := body[field]; !ok {
			t.Errorf("%s must be present: the update is a full replace", field)
		}
	}
}

// The update carries the id in the body, and the path has no id at all.
func TestUpdateDocumentSetPutsIDInBody(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	err := c.UpdateDocumentSet(context.Background(), DocumentSetUpdate{
		ID:        12,
		Name:      "engineering",
		CCPairIDs: []int64{3},
		Users:     []string{},
		Groups:    []int64{},
	})
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/manage/admin/document-set" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	if body := bodyAsMap(t, captured.Body); body["id"] != float64(12) {
		t.Errorf("unexpected body: %v", body)
	}
}

func TestGetDocumentSetParsesSummary(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{
		"id": 12,
		"name": "engineering",
		"description": null,
		"cc_pair_summaries": [
			{"id": 3, "name": "docs", "source": "mock_connector", "access_type": "public"},
			{"id": 4, "name": "wiki", "source": "mock_connector", "access_type": "public"}
		],
		"is_up_to_date": false,
		"is_public": true,
		"users": [],
		"groups": [7],
		"federated_connector_summaries": []
	}`)
	set, err := c.GetDocumentSet(context.Background(), 12)
	if err != nil {
		t.Fatal(err)
	}
	if captured.Path != "/manage/admin/document-set/12" {
		t.Errorf("path = %s", captured.Path)
	}
	if set.Description != nil {
		t.Errorf("description should stay nil when the server returns null")
	}
	ids := set.CCPairIDs()
	if len(ids) != 2 || ids[0] != 3 || ids[1] != 4 {
		t.Errorf("cc-pair ids = %v, want [3 4]", ids)
	}
	if set.IsUpToDate {
		t.Error("is_up_to_date should be false")
	}
}

func TestDeleteDocumentSetPath(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.DeleteDocumentSet(context.Background(), 12); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodDelete || captured.Path != "/manage/admin/document-set/12" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
}
