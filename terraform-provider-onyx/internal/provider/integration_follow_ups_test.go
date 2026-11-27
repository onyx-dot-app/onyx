package provider

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework/attr"
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

func TestUpdateSendsCredentialsForANewVersionOrAChangedConnectionWithoutAWorkingConnection(t *testing.T) {
	base := integrationResourceModel{
		ServerURL:                        types.StringValue("https://mcp.example.com/mcp"),
		OpenAPIDocument:                  types.StringNull(),
		HeaderTemplate:                   types.MapNull(types.StringType),
		AuthMode:                         types.StringValue("none"),
		AuthMethod:                       types.StringNull(),
		OrganizationCredentialsWOVersion: types.Int64Value(1),
	}
	newVersion := base
	newVersion.OrganizationCredentialsWOVersion = types.Int64Value(2)
	newURL := base
	newURL.ServerURL = types.StringValue("https://mcp2.example.com/mcp")
	newDocument := base
	newDocument.OpenAPIDocument = types.StringValue(`{"openapi":"3.0.0"}`)
	newHeaders := base
	newHeaders.HeaderTemplate = types.MapValueMust(types.StringType, map[string]attr.Value{
		"X-Secret": types.StringValue("{secret}"),
	})
	newSignIn := base
	newSignIn.AuthMode = types.StringValue("shared")
	serverURL := "https://mcp.example.com/mcp"
	status := func(state string) *client.Integration {
		return &client.Integration{
			AuthMode:           "none",
			Config:             client.IntegrationConfig{Shape: client.IntegrationShapeMCPServer, ServerURL: &serverURL},
			OrganizationStatus: &client.IntegrationStatus{State: state},
		}
	}
	newServerURL := "https://mcp2.example.com/mcp"
	failedEarlierApply := status("needs_reconnect")
	failedEarlierApply.Config.ServerURL = &newServerURL

	connected := status("connected")
	cases := []struct {
		name   string
		plan   integrationResourceModel
		before *client.Integration
		after  *client.Integration
		want   bool
	}{
		{"a new credentials version", newVersion, status("needs_reconnect"), status("needs_reconnect"), true},
		{"a new server URL that needs reconnect", newURL, connected, status("needs_reconnect"), true},
		{"a new server URL with no connection yet", newURL, &client.Integration{}, status("not_set_up"), true},
		{"a new OpenAPI document that needs reconnect", newDocument, connected, status("needs_reconnect"), true},
		{"a new OpenAPI document that keeps the connection", newDocument, connected, connected, false},
		{"a new header field that needs reconnect", newHeaders, connected, status("needs_reconnect"), true},
		{"a header edit of a key rejected before", newHeaders, status("needs_reconnect"), status("needs_reconnect"), false},
		{"a retry of a server URL change that an earlier apply left unsigned", newURL, failedEarlierApply, status("needs_reconnect"), true},
		{"a new shared sign-in with no connection yet", newSignIn, status("not_set_up"), status("not_set_up"), true},
		{"an unrelated update of a rejected key", base, status("needs_reconnect"), status("needs_reconnect"), false},
		{"a new server URL with no shared sign-in", newURL, &client.Integration{}, &client.Integration{}, false},
	}
	for _, c := range cases {
		if got := sendsOrganizationCredentials(context.Background(), c.plan, base, c.before, c.after); got != c.want {
			t.Errorf("%s: sends = %v, want %v", c.name, got, c.want)
		}
	}
}

func TestRestrictAccessTurnsOffAndHidesBeforeTheUpdate(t *testing.T) {
	var calls []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls = append(calls, r.Method+" "+r.URL.Path)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id": 7, "kind": "mcp", "enabled": false, "installation_policy": "AVAILABLE"}`))
	}))
	t.Cleanup(server.Close)
	r := &integrationResource{client: client.NewClient(client.Config{ServerURL: server.URL, APIKey: "on_test_key"})}
	hidden := integrationResourceModel{Enabled: types.BoolValue(false), InstallationPolicy: types.StringValue("NOT_AVAILABLE")}
	shown := integrationResourceModel{Enabled: types.BoolValue(true), InstallationPolicy: types.StringValue("AVAILABLE")}

	cases := []struct {
		name    string
		plan    integrationResourceModel
		current *client.Integration
		want    []string
	}{
		{"turned off and made not available", hidden, &client.Integration{Enabled: true, InstallationPolicy: "AVAILABLE"},
			[]string{"PATCH /admin/integrations/7", "PUT /admin/integrations/7/installation-policy"}},
		{"already off and not available", hidden, &client.Integration{InstallationPolicy: "NOT_AVAILABLE"}, nil},
		{"turned on and made available", shown, &client.Integration{InstallationPolicy: "NOT_AVAILABLE"}, nil},
	}
	for _, c := range cases {
		calls = nil
		var diags diag.Diagnostics
		if !r.restrictAccess(context.Background(), 7, c.plan, c.current, &diags) || diags.HasError() {
			t.Fatalf("%s: restrictAccess: %v", c.name, diags)
		}
		if !slices.Equal(calls, c.want) {
			t.Errorf("%s: calls = %v, want %v", c.name, calls, c.want)
		}
	}
}

func TestCreateKeepsAnIntegrationMeantToBeOffPrivate(t *testing.T) {
	cases := []struct {
		enabled types.Bool
		policy  string
		want    bool
	}{
		{types.BoolValue(false), "AVAILABLE", false},
		{types.BoolValue(true), "AVAILABLE", true},
		{types.BoolNull(), "REQUIRED", true},
		{types.BoolValue(true), "NOT_AVAILABLE", false},
	}
	for _, c := range cases {
		plan := integrationResourceModel{Enabled: c.enabled, InstallationPolicy: types.StringValue(c.policy)}
		if got := createsForOrganization(plan); got != c.want {
			t.Errorf("enabled %v, %s: for organization = %v, want %v", c.enabled, c.policy, got, c.want)
		}
	}
}
