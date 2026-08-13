package client

import (
	"context"
	"net/http"
	"testing"
)

const apiKeyJSON = `{
	"api_key_id": 7,
	"api_key_display": "on_****abcd",
	"api_key": "on_full_secret_key",
	"api_key_name": "terraform",
	"api_key_role": "admin",
	"user_id": "9b9284a6-16b5-4a3c-bfa4-lol"
}`

func strPtr(s string) *string { return &s }

func TestCreateAPIKey(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, apiKeyJSON)
	desc, err := c.CreateAPIKey(context.Background(), APIKeyArgs{Name: strPtr("terraform"), Role: "admin"})
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPost || captured.Path != "/admin/api-key" {
		t.Errorf("got %s %s, want POST /admin/api-key", captured.Method, captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	if body["name"] != "terraform" || body["role"] != "admin" {
		t.Errorf("unexpected body: %s", captured.Body)
	}
	if desc.APIKeyID != 7 || desc.APIKey == nil || *desc.APIKey != "on_full_secret_key" {
		t.Errorf("unexpected descriptor: %+v", desc)
	}
}

func TestCreateAPIKeyNullName(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, apiKeyJSON)
	if _, err := c.CreateAPIKey(context.Background(), APIKeyArgs{Role: "basic"}); err != nil {
		t.Fatal(err)
	}
	body := bodyAsMap(t, captured.Body)
	if v, present := body["name"]; !present || v != nil {
		t.Errorf("name should be explicitly null, body: %s", captured.Body)
	}
}

func TestGetAPIKeyScansList(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `[`+apiKeyJSON+`]`)
	desc, err := c.GetAPIKey(context.Background(), 7)
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodGet || captured.Path != "/admin/api-key" {
		t.Errorf("got %s %s, want GET /admin/api-key", captured.Method, captured.Path)
	}
	if desc.APIKeyRole != "admin" {
		t.Errorf("unexpected descriptor: %+v", desc)
	}

	if _, err := c.GetAPIKey(context.Background(), 999); !IsNotFound(err) {
		t.Errorf("missing id should return a 404 APIError, got %v", err)
	}
}

func TestUpdateAPIKey(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, apiKeyJSON)
	if _, err := c.UpdateAPIKey(context.Background(), 7, APIKeyArgs{Name: strPtr("renamed"), Role: "basic"}); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/admin/api-key/7" {
		t.Errorf("got %s %s, want PATCH /admin/api-key/7", captured.Method, captured.Path)
	}
}

func TestDeleteAPIKey(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.DeleteAPIKey(context.Background(), 7); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodDelete || captured.Path != "/admin/api-key/7" {
		t.Errorf("got %s %s, want DELETE /admin/api-key/7", captured.Method, captured.Path)
	}
}

func TestRegenerateAPIKey(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, apiKeyJSON)
	desc, err := c.RegenerateAPIKey(context.Background(), 7)
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPost || captured.Path != "/admin/api-key/7/regenerate" {
		t.Errorf("got %s %s, want POST /admin/api-key/7/regenerate", captured.Method, captured.Path)
	}
	if desc.APIKey == nil {
		t.Error("regenerate response should carry the new plaintext key")
	}
}
