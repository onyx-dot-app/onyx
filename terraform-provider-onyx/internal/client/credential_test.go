package client

import (
	"context"
	"net/http"
	"testing"
)

const credentialJSON = `{
	"id": 12,
	"credential_json": {"confluence_access_token": "abc****"},
	"admin_public": true,
	"source": "confluence",
	"name": "terraform",
	"curator_public": false,
	"user_id": "9b9284a6-16b5-4a3c-bfa4-lol"
}`

func testCredentialUpsert() CredentialUpsert {
	return CredentialUpsert{
		CredentialJSON: map[string]any{"confluence_access_token": "real-secret"},
		AdminPublic:    true,
		Source:         "confluence",
		Name:           strPtr("terraform"),
		Groups:         []int64{},
	}
}

func TestCreateCredential(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"id": 12}`)
	id, err := c.CreateCredential(context.Background(), testCredentialUpsert())
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPost || captured.Path != "/manage/credential" {
		t.Errorf("got %s %s, want POST /manage/credential", captured.Method, captured.Path)
	}
	if id != 12 {
		t.Errorf("got id %d, want 12", id)
	}
	body := bodyAsMap(t, captured.Body)
	payload, ok := body["credential_json"].(map[string]any)
	if !ok || payload["confluence_access_token"] != "real-secret" {
		t.Errorf("configured secret must be sent verbatim, body: %s", captured.Body)
	}
	// Pydantic rejects a null where it expects a list.
	if groups, ok := body["groups"].([]any); !ok || len(groups) != 0 {
		t.Errorf("groups must serialize as an empty array, body: %s", captured.Body)
	}
}

func TestGetCredentialScansAdminList(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `[`+credentialJSON+`]`)
	remote, err := c.GetCredential(context.Background(), 12)
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodGet || captured.Path != "/manage/admin/credential" {
		t.Errorf("got %s %s, want GET /manage/admin/credential", captured.Method, captured.Path)
	}
	if remote.Source != "confluence" || remote.Name == nil || *remote.Name != "terraform" {
		t.Errorf("unexpected credential: %+v", remote)
	}

	// The get-by-id endpoint answers 401 for a missing credential, so the
	// list scan is what turns "gone" into a 404.
	if _, err := c.GetCredential(context.Background(), 999); !IsNotFound(err) {
		t.Errorf("missing id should return a 404 APIError, got %v", err)
	}
}

func TestReplaceCredentialJSON(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, credentialJSON)
	if err := c.ReplaceCredentialJSON(context.Background(), 12, testCredentialUpsert()); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/manage/credential/12" {
		t.Errorf("got %s %s, want PATCH /manage/credential/12", captured.Method, captured.Path)
	}
}

func TestSetCredentialName(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, credentialJSON)
	payload := map[string]any{"confluence_access_token": "real-secret"}
	if err := c.SetCredentialName(context.Background(), 12, "renamed", payload); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPut || captured.Path != "/manage/admin/credential/12" {
		t.Errorf("got %s %s, want PUT /manage/admin/credential/12", captured.Method, captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	if body["name"] != "renamed" {
		t.Errorf("unexpected body: %s", captured.Body)
	}
	// The endpoint merges the payload, so it must carry the full desired value.
	sent, ok := body["credential_json"].(map[string]any)
	if !ok || sent["confluence_access_token"] != "real-secret" {
		t.Errorf("rename must resend the full payload, body: %s", captured.Body)
	}
}

func TestDeleteCredential(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)
	if err := c.DeleteCredential(context.Background(), 12); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodDelete || captured.Path != "/manage/admin/credential/12" {
		t.Errorf("got %s %s, want DELETE /manage/admin/credential/12", captured.Method, captured.Path)
	}
}
