package client

import (
	"context"
	"net/http"
	"testing"
)

func TestCreateCCPairRequest(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"success": true, "message": "created", "data": 77}`)
	id, err := c.CreateCCPair(context.Background(), 3, 5, CCPairCreate{
		Name:            "docs",
		AccessType:      "public",
		AutoSyncOptions: nil,
		Groups:          []int64{},
		ProcessingMode:  "REGULAR",
	})
	if err != nil {
		t.Fatal(err)
	}
	if id != 77 {
		t.Errorf("cc-pair id = %d, want 77", id)
	}
	if captured.Method != http.MethodPut {
		t.Errorf("method = %s, want PUT", captured.Method)
	}
	if captured.Path != "/manage/connector/3/credential/5" {
		t.Errorf("path = %s", captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	if body["name"] != "docs" || body["access_type"] != "public" {
		t.Errorf("unexpected body: %v", body)
	}
	// Full-replace bodies carry every field, so groups must be sent as an
	// empty list rather than omitted.
	if _, ok := body["groups"]; !ok {
		t.Error("groups must be present in the request body")
	}
}

// A duplicate association answers 200 with success=false and puts the
// connector id in data, so an unchecked client would store the wrong id.
func TestCreateCCPairRejectsNoOpResponse(t *testing.T) {
	c, _ := newTestServer(t, http.StatusOK,
		`{"success": false, "message": "Connector 3 already has Credential 5", "data": 3}`)
	id, err := c.CreateCCPair(context.Background(), 3, 5, CCPairCreate{Name: "docs", AccessType: "public"})
	if err == nil {
		t.Fatalf("expected an error for a no-op association, got id %d", id)
	}
	if id != 0 {
		t.Errorf("id = %d, want 0 when the association was not created", id)
	}
}

func TestGetCCPairParsesNestedIDs(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{
		"id": 77,
		"name": "docs",
		"status": "PAUSED",
		"access_type": "private",
		"num_docs_indexed": 12,
		"last_index_attempt_status": "success",
		"deletion_failure_message": null,
		"indexing": false,
		"connector": {"id": 3, "name": "c", "source": "mock_connector"},
		"credential": {"id": 5, "source": "mock_connector"}
	}`)
	pair, err := c.GetCCPair(context.Background(), 77)
	if err != nil {
		t.Fatal(err)
	}
	if captured.Path != "/manage/admin/cc-pair/77" {
		t.Errorf("path = %s", captured.Path)
	}
	if pair.Connector.ID != 3 || pair.Credential.ID != 5 {
		t.Errorf("connector/credential ids = %d/%d, want 3/5", pair.Connector.ID, pair.Credential.ID)
	}
	if pair.Status != CCPairStatusPaused || pair.AccessType != "private" {
		t.Errorf("unexpected pair: %+v", pair)
	}
}

func TestSetCCPairNameUsesQueryParam(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"success": true, "message": "ok", "data": 77}`)
	if err := c.SetCCPairName(context.Background(), 77, "name with spaces & symbols"); err != nil {
		t.Fatal(err)
	}
	want := "/manage/admin/cc-pair/77/name?new_name=name+with+spaces+%26+symbols"
	if captured.Path != want {
		t.Errorf("path = %s, want %s", captured.Path, want)
	}
	if len(captured.Body) != 0 {
		t.Errorf("expected no request body, got %s", captured.Body)
	}
}

func TestSetCCPairStatusBody(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"message": "OK"}`)
	if err := c.SetCCPairStatus(context.Background(), 77, CCPairStatusActive); err != nil {
		t.Fatal(err)
	}
	if captured.Path != "/manage/admin/cc-pair/77/status" {
		t.Errorf("path = %s", captured.Path)
	}
	if body := bodyAsMap(t, captured.Body); body["status"] != "ACTIVE" {
		t.Errorf("unexpected body: %v", body)
	}
}

// Deletion addresses the pair by its two halves, not by its own id.
func TestDeleteCCPairSendsIdentifier(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.DeleteCCPair(context.Background(), 3, 5); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPost || captured.Path != "/manage/admin/deletion-attempt" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	if body["connector_id"] != float64(3) || body["credential_id"] != float64(5) {
		t.Errorf("unexpected body: %v", body)
	}
}
