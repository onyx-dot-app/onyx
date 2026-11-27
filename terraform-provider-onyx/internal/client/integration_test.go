package client

import (
	"context"
	"net/http"
	"testing"
)

const integrationDetail = `{
  "id": 7, "kind": "mcp", "shape": "mcp_server", "name": "Weather",
  "description": null, "enabled": true, "auth_mode": "shared", "auth_method": "api_key",
  "installation_policy": "AVAILABLE", "header_template": {"Authorization": "Bearer {api_key}"},
  "config": {"shape": "mcp_server", "server_url": "https://mcp.example.com/mcp", "transport": "STREAMABLE_HTTP"}
}`

func TestCreateIntegration(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, integrationDetail)
	url := "https://mcp.example.com/mcp"
	method := "api_key"
	integration, err := c.CreateIntegration(context.Background(), IntegrationCreate{
		ForOrganization: true,
		Name:            "Weather",
		AuthMode:        "shared",
		AuthMethod:      &method,
		HeaderTemplate:  map[string]string{"Authorization": "Bearer {api_key}"},
		Config:          IntegrationConfig{Shape: IntegrationShapeMCPServer, ServerURL: &url},
	})
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPost || captured.Path != "/admin/integrations" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	config := body["config"].(map[string]any)
	if body["for_organization"] != true || config["shape"] != "mcp_server" || config["server_url"] != url {
		t.Errorf("body = %v", body)
	}
	if _, sent := config["openapi_document"]; sent {
		t.Errorf("an MCP config must not send openapi_document: %v", config)
	}
	if integration.ID != 7 || integration.Config.ServerURL == nil || *integration.Config.ServerURL != url {
		t.Errorf("integration = %+v", integration)
	}
}

func TestUpdateIntegrationSendsEveryField(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, integrationDetail)
	doc := "openapi: 3.0.0"
	if _, err := c.UpdateIntegration(context.Background(), 7, IntegrationUpdate{
		Name:     "Weather",
		AuthMode: "none",
		Config:   IntegrationConfig{Shape: IntegrationShapeOpenAPI, OpenAPIDocument: &doc},
	}); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/admin/integrations/7" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	body := bodyAsMap(t, captured.Body)
	// Onyx keeps the fields that are not sent, so a removed value must be sent
	// as null or empty to clear it.
	for _, key := range []string{"description", "auth_method"} {
		if value, sent := body[key]; !sent || value != nil {
			t.Errorf("%s = %v, sent = %v; want an explicit null", key, value, sent)
		}
	}
	if headers, ok := body["header_template"].(map[string]any); !ok || len(headers) != 0 {
		t.Errorf("header_template = %v, want {}", body["header_template"])
	}
	if _, sent := body["enabled"]; sent {
		t.Errorf("a full update must not send enabled: %v", body)
	}
}

func TestIntegrationFollowUpRoutes(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, integrationDetail)
	ctx := context.Background()

	if _, err := c.UpdateIntegrationEnabled(ctx, 7, false); err != nil {
		t.Fatal(err)
	}
	if body := bodyAsMap(t, captured.Body); captured.Method != http.MethodPatch || len(body) != 1 || body["enabled"] != false {
		t.Errorf("%s %v", captured.Method, body)
	}

	if err := c.SetIntegrationInstallationPolicy(ctx, 7, "REQUIRED"); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPut || captured.Path != "/admin/integrations/7/installation-policy" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	if body := bodyAsMap(t, captured.Body); body["installation_policy"] != "REQUIRED" {
		t.Errorf("body = %v", body)
	}

	if err := c.SaveIntegrationOrganizationConnection(ctx, 7, map[string]string{"api_key": "k"}); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPut || captured.Path != "/admin/integrations/7/organization-connection" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
	fields, _ := bodyAsMap(t, captured.Body)["fields"].(map[string]any)
	if fields["api_key"] != "k" {
		t.Errorf("fields = %v", fields)
	}

	if err := c.RefreshIntegrationActions(ctx, 7); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPost || captured.Path != "/admin/integrations/7/actions/refresh" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}

	if err := c.DeleteIntegration(ctx, 7); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodDelete || captured.Path != "/admin/integrations/7" {
		t.Errorf("%s %s", captured.Method, captured.Path)
	}
}
