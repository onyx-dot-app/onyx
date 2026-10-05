package client

import (
	"context"
	"net/http"
	"testing"
)

const connectorJSON = `{
	"id": 5,
	"name": "docs site",
	"source": "web",
	"input_type": "load_state",
	"connector_specific_config": {"base_url": "https://example.com", "web_connector_type": "recursive"},
	"refresh_freq": 86400,
	"prune_freq": 604800,
	"indexing_start": null,
	"credential_ids": [3]
}`

func testConnectorUpsert() ConnectorUpsert {
	return ConnectorUpsert{
		Name:                    "docs site",
		Source:                  "web",
		InputType:               "load_state",
		ConnectorSpecificConfig: map[string]any{"base_url": "https://example.com"},
		AccessType:              "public",
		Groups:                  []int64{},
	}
}

func TestCreateConnector(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"id": 5}`)
	id, err := c.CreateConnector(context.Background(), testConnectorUpsert())
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPost || captured.Path != "/manage/admin/connector" {
		t.Errorf("got %s %s, want POST /manage/admin/connector", captured.Method, captured.Path)
	}
	if id != 5 {
		t.Errorf("got id %d, want 5", id)
	}
	body := bodyAsMap(t, captured.Body)
	if body["access_type"] != "public" {
		t.Errorf("unexpected body: %s", captured.Body)
	}
	// Omitting these deletes the schedule server-side, so they are always sent.
	for _, field := range []string{"refresh_freq", "prune_freq", "indexing_start"} {
		if v, present := body[field]; !present || v != nil {
			t.Errorf("%s should be explicitly null, body: %s", field, captured.Body)
		}
	}
}

func TestGetConnector(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, connectorJSON)
	remote, err := c.GetConnector(context.Background(), 5)
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodGet || captured.Path != "/manage/connector/5" {
		t.Errorf("got %s %s, want GET /manage/connector/5", captured.Method, captured.Path)
	}
	if remote.RefreshFreq == nil || *remote.RefreshFreq != 86400 {
		t.Errorf("unexpected connector: %+v", remote)
	}
	if len(remote.CredentialIDs) != 1 || remote.CredentialIDs[0] != 3 {
		t.Errorf("unexpected credential ids: %+v", remote.CredentialIDs)
	}
}

func TestGetConnectorNotFound(t *testing.T) {
	c, _ := newTestServer(t, http.StatusNotFound, `{"detail": "Connector 5 does not exist"}`)
	_, err := c.GetConnector(context.Background(), 5)
	if !IsNotFound(err) {
		t.Fatalf("want a 404 APIError, got %v", err)
	}
}

func TestUpdateConnector(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, connectorJSON)
	remote, err := c.UpdateConnector(context.Background(), 5, testConnectorUpsert())
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/manage/admin/connector/5" {
		t.Errorf("got %s %s, want PATCH /manage/admin/connector/5", captured.Method, captured.Path)
	}
	// The server rewrites an unset prune_freq to its default, so the response
	// is the source of truth.
	if remote.PruneFreq == nil || *remote.PruneFreq != 604800 {
		t.Errorf("update must return the stored prune_freq, got %+v", remote.PruneFreq)
	}
}

func TestListConnectors(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `[`+connectorJSON+`]`)
	connectors, err := c.ListConnectors(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if captured.Path != "/manage/connector" {
		t.Errorf("got %s, want /manage/connector", captured.Path)
	}
	if len(connectors) != 1 || connectors[0].Name != "docs site" {
		t.Errorf("unexpected connectors: %+v", connectors)
	}
}

func TestDeleteConnector(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"success": true, "message": "", "data": 5}`)
	if err := c.DeleteConnector(context.Background(), 5); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodDelete || captured.Path != "/manage/admin/connector/5" {
		t.Errorf("got %s %s, want DELETE /manage/admin/connector/5", captured.Method, captured.Path)
	}
}
