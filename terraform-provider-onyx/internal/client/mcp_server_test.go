package client

import (
	"context"
	"net/http"
	"testing"
)

const mcpServerResponse = `{
	"id": 3,
	"name": "weather",
	"description": "public weather tools",
	"server_url": "https://mcp.example.com/mcp",
	"owner": "admin@example.com",
	"transport": "STREAMABLE_HTTP",
	"auth_type": "API_TOKEN",
	"auth_performer": "ADMIN",
	"status": "CREATED",
	"is_public": true,
	"groups": [],
	"users": [],
	"available_in_craft": false,
	"last_refreshed_at": null,
	"tool_count": 0,
	"auth_template": {"headers": {"Authorization": "Bearer {api_key}"}, "required_fields": ["api_key"]},
	"admin_credentials": {"api_key": "••••••••••••"}
}`

func TestUpsertMCPServerAlwaysSendsDescription(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"server_id": 3}`)
	id, err := c.UpsertMCPServer(context.Background(), MCPServerWrite{
		Name:          "weather",
		Description:   "",
		ServerURL:     "https://mcp.example.com/mcp",
		AuthType:      MCPAuthNone,
		AuthPerformer: MCPPerformerAdmin,
		Transport:     "STREAMABLE_HTTP",
	})
	if err != nil {
		t.Fatal(err)
	}
	if id != 3 {
		t.Errorf("want the new server id, got %d", id)
	}
	if captured.Method != http.MethodPost || captured.Path != "/admin/mcp/servers/create" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}

	body := bodyAsMap(t, captured.Body)
	// Onyx preserves the stored description when the field is missing, so an
	// empty one has to travel as "" for a cleared description to clear.
	description, ok := body["description"]
	if !ok {
		t.Fatal("description must be sent even when empty, or clearing it silently keeps the old value")
	}
	if description != "" {
		t.Errorf("want an empty description, got %v", description)
	}
	if _, ok := body["existing_server_id"]; ok {
		t.Error("a create must not name an existing server")
	}
	// Absent means "leave the stored access alone", which is not the same as
	// an empty list.
	for _, field := range []string{"groups", "users"} {
		if _, ok := body[field]; ok {
			t.Errorf("%s must be omitted when the configuration does not state it", field)
		}
	}
}

func TestUpsertMCPServerUpdateCarriesTheChangedFlags(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"server_id": 3}`)
	existing := int64(3)
	token := "shhh"
	public := false
	groups := []int64{4}
	users := []string{"11111111-2222-3333-4444-555555555555"}
	if _, err := c.UpsertMCPServer(context.Background(), MCPServerWrite{
		ExistingServerID:        &existing,
		Name:                    "weather",
		ServerURL:               "https://mcp.example.com/mcp",
		AuthType:                MCPAuthAPIToken,
		AuthPerformer:           MCPPerformerAdmin,
		Transport:               "STREAMABLE_HTTP",
		APIToken:                &token,
		APITokenChanged:         true,
		AdminCredentials:        map[string]string{"api_key": "shhh"},
		AdminCredentialsChanged: map[string]bool{"api_key": true},
		IsPublic:                &public,
		Groups:                  &groups,
		Users:                   &users,
	}); err != nil {
		t.Fatal(err)
	}

	body := bodyAsMap(t, captured.Body)
	if body["existing_server_id"] != float64(3) {
		t.Errorf("an update must name the server it edits, got %v", body["existing_server_id"])
	}
	if body["api_token_changed"] != true {
		t.Error("without the changed flag Onyx keeps the token it already holds")
	}
	if body["api_token"] != "shhh" {
		t.Errorf("want the configured token, got %v", body["api_token"])
	}
	changed, ok := body["admin_credentials_changed"].(map[string]any)
	if !ok || changed["api_key"] != true {
		t.Errorf("every credential sent must be flagged as changed: %v", body["admin_credentials_changed"])
	}
	if body["is_public"] != false {
		t.Errorf("want is_public false, got %v", body["is_public"])
	}
	if _, ok := body["groups"]; !ok {
		t.Error("a stated group list must be sent")
	}
	if _, ok := body["users"]; !ok {
		t.Error("a stated user list must be sent")
	}
}

func TestGetMCPServerReadsTheAdminPath(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, mcpServerResponse)
	server, err := c.GetMCPServer(context.Background(), 3)
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodGet || captured.Path != "/admin/mcp/servers/3" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	if server.Name != "weather" || server.Status != "CREATED" {
		t.Errorf("unexpected server: %+v", server)
	}
	if server.AuthTemplate == nil || server.AuthTemplate.Headers["Authorization"] != "Bearer {api_key}" {
		t.Errorf("the auth template must survive the read: %+v", server.AuthTemplate)
	}
	if server.LastRefreshedAt != nil {
		t.Errorf("a server whose tools were never listed has no refresh time, got %v", *server.LastRefreshedAt)
	}
}

func TestPatchMCPServerCarriesCraftAvailability(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, mcpServerResponse)
	available := true
	if _, err := c.PatchMCPServer(context.Background(), 3, MCPServerPatch{AvailableInCraft: &available}); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/admin/mcp/server/3" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	if body["available_in_craft"] != true {
		t.Errorf("want available_in_craft true, got %v", body["available_in_craft"])
	}
}

func TestDeleteMCPServer(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `{"success": true}`)
	if err := c.DeleteMCPServer(context.Background(), 3); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodDelete || captured.Path != "/admin/mcp/server/3" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
}

func TestDeleteMCPServerReportsAMissingServerAsNotFound(t *testing.T) {
	c, _ := newTestServer(t, http.StatusNotFound, `{"detail": "MCP server not found"}`)
	err := c.DeleteMCPServer(context.Background(), 3)
	if err == nil {
		t.Fatal("want an error for a missing server")
	}
	// The destroy tolerates this, so it has to be recognisable.
	if !IsNotFound(err) {
		t.Errorf("want a not-found error, got %v", err)
	}
}
