package client

import (
	"context"
	"net/http"
	"testing"
)

func TestCreateAgentLabel(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"id": 4, "name": "Engineering"}`)
	label, err := c.CreateAgentLabel(context.Background(), "Engineering")
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPost || captured.Path != "/persona/labels" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	if body := bodyAsMap(t, captured.Body); body["name"] != "Engineering" {
		t.Errorf("name = %v", body["name"])
	}
	if label.ID != 4 {
		t.Errorf("id = %d, want 4", label.ID)
	}
}

func TestGetAgentLabelMissingIsNotFound(t *testing.T) {
	c, _ := newTestServer(t, http.StatusOK, `[{"id": 4, "name": "Engineering"}]`)
	if _, err := c.GetAgentLabel(context.Background(), 5); !IsNotFound(err) {
		t.Errorf("want a not-found error, got %v", err)
	}
	label, err := c.GetAgentLabel(context.Background(), 4)
	if err != nil || label.Name != "Engineering" {
		t.Errorf("label = %v, err = %v", label, err)
	}
}

func TestRenameAgentLabel(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.RenameAgentLabel(context.Background(), 4, "Platform"); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/admin/persona/label/4" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	if body := bodyAsMap(t, captured.Body); body["label_name"] != "Platform" {
		t.Errorf("label_name = %v", body["label_name"])
	}
}
