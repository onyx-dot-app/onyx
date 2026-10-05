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
	"groups": [{"id": 3, "name": "Admin"}],
	"user_id": "9b9284a6-16b5-4a3c-bfa4-lol"
}`

func strPtr(s string) *string { return &s }

func TestCreateAPIKey(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, apiKeyJSON)
	desc, err := c.CreateAPIKey(context.Background(), APIKeyArgs{Name: strPtr("terraform"), GroupIDs: []int64{3}})
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPost || captured.Path != "/admin/api-key" {
		t.Errorf("got %s %s, want POST /admin/api-key", captured.Method, captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	groups, _ := body["group_ids"].([]any)
	if body["name"] != "terraform" || len(groups) != 1 || groups[0] != float64(3) {
		t.Errorf("unexpected body: %s", captured.Body)
	}
	if desc.APIKeyID != 7 || desc.APIKey == nil || *desc.APIKey != "on_full_secret_key" {
		t.Errorf("unexpected descriptor: %+v", desc)
	}
}

func TestCreateAPIKeyNullName(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, apiKeyJSON)
	if _, err := c.CreateAPIKey(context.Background(), APIKeyArgs{GroupIDs: []int64{}}); err != nil {
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
	if len(desc.Groups) != 1 || desc.Groups[0].ID != 3 {
		t.Errorf("unexpected descriptor: %+v", desc)
	}

	if _, err := c.GetAPIKey(context.Background(), 999); !IsNotFound(err) {
		t.Errorf("missing id should return a 404 APIError, got %v", err)
	}
}

func TestUpdateAPIKey(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, apiKeyJSON)
	if _, err := c.UpdateAPIKey(context.Background(), 7, APIKeyArgs{Name: strPtr("renamed"), GroupIDs: []int64{3}}); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/admin/api-key/7" {
		t.Errorf("got %s %s, want PATCH /admin/api-key/7", captured.Method, captured.Path)
	}
}

// Args with no GroupIDs set: nil marshals to JSON null, which the backend rejects
// with a 422 instead of reading as "no groups".
func TestAPIKeyArgsAlwaysSendGroupIDs(t *testing.T) {
	for _, tc := range []struct {
		name string
		call func(*Client) error
	}{
		{"create", func(c *Client) error {
			_, err := c.CreateAPIKey(context.Background(), APIKeyArgs{})
			return err
		}},
		{"update", func(c *Client) error {
			_, err := c.UpdateAPIKey(context.Background(), 7, APIKeyArgs{})
			return err
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c, captured := newTestServer(t, http.StatusOK, apiKeyJSON)
			if err := tc.call(c); err != nil {
				t.Fatal(err)
			}
			value, present := bodyAsMap(t, captured.Body)["group_ids"]
			if !present || value == nil {
				t.Errorf("group_ids must serialize as a list, body: %s", captured.Body)
			}
		})
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
