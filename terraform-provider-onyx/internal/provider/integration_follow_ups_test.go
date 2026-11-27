package provider

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

// followUpCalls runs applyFollowUps for a new shared MCP integration that
// Onyx created turned on, and returns the requests in order.
func followUpCalls(t *testing.T, enabled bool) []string {
	t.Helper()
	return followUpCallsWith(t, enabled, map[string]string{"api_key": "k"}, false)
}

func followUpCallsWith(t *testing.T, enabled bool, credentials map[string]string, serverChanged bool) []string {
	t.Helper()
	var calls []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls = append(calls, r.Method+" "+r.URL.Path)
		w.Header().Set("Content-Type", "application/json")
		body, _ := json.Marshal(map[string]any{
			"id": 7, "name": "tickets", "kind": "mcp", "enabled": enabled,
			"installation_policy": "AVAILABLE", "auth_mode": "shared",
			"config": map[string]any{"shape": "mcp_server"},
		})
		_, _ = w.Write(body)
	}))
	t.Cleanup(server.Close)
	r := &integrationResource{client: client.NewClient(client.Config{ServerURL: server.URL, APIKey: "on_test_key"})}
	plan := integrationResourceModel{Enabled: types.BoolValue(enabled), InstallationPolicy: types.StringNull()}
	remote := &client.Integration{ID: 7, Kind: "mcp", Enabled: true, InstallationPolicy: "AVAILABLE"}
	var diags diag.Diagnostics
	r.applyFollowUps(context.Background(), 7, plan, remote, credentials, serverChanged, &diags)
	if diags.HasError() {
		t.Fatalf("applyFollowUps: %v", diags)
	}
	return calls
}

func TestApplyFollowUpsTurnsOffBeforeSavingCredentials(t *testing.T) {
	calls := followUpCalls(t, false)
	want := []string{
		"PATCH /admin/integrations/7",
		"PUT /admin/integrations/7/organization-connection",
		"POST /admin/integrations/7/actions/refresh",
		"GET /admin/integrations/7",
	}
	if !slices.Equal(calls, want) {
		t.Fatalf("calls = %v, want %v", calls, want)
	}
}

func TestApplyFollowUpsSkipsSwitchWhenAlreadyOn(t *testing.T) {
	calls := followUpCalls(t, true)
	if slices.Contains(calls, "PATCH /admin/integrations/7") {
		t.Fatalf("calls = %v, want no switch change", calls)
	}
}

func TestApplyFollowUpsRefreshesActionsAfterServerChange(t *testing.T) {
	calls := followUpCallsWith(t, true, nil, true)
	want := []string{
		"POST /admin/integrations/7/actions/refresh",
		"GET /admin/integrations/7",
	}
	if !slices.Equal(calls, want) {
		t.Fatalf("calls = %v, want %v", calls, want)
	}
}

func TestApplyFollowUpsSkipsRefreshWithoutCredentialsOrServerChange(t *testing.T) {
	calls := followUpCallsWith(t, true, nil, false)
	if slices.Contains(calls, "POST /admin/integrations/7/actions/refresh") {
		t.Fatalf("calls = %v, want no action refresh", calls)
	}
}

func TestUpdateSendsCredentialsWhenTheirDestinationChanges(t *testing.T) {
	base := integrationResourceModel{
		ServerURL:                        types.StringValue("https://mcp.example.com/mcp"),
		OpenAPIDocument:                  types.StringNull(),
		OrganizationCredentialsWOVersion: types.Int64Value(1),
	}
	newURL := base
	newURL.ServerURL = types.StringValue("https://mcp2.example.com/mcp")
	newDocument := base
	newDocument.OpenAPIDocument = types.StringValue(`{"openapi":"3.0.0"}`)
	newVersion := base
	newVersion.OrganizationCredentialsWOVersion = types.Int64Value(2)

	for name, plan := range map[string]integrationResourceModel{
		"server URL": newURL, "OpenAPI document": newDocument, "credentials version": newVersion,
	} {
		if !sendsOrganizationCredentials(plan, base) {
			t.Errorf("a new %s does not send the credentials", name)
		}
	}
	if sendsOrganizationCredentials(base, base) {
		t.Error("an unchanged plan sends the credentials")
	}
}
