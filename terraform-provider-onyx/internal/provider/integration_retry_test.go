package provider

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"sync"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
)

// fakeIntegrationServer is an Onyx with one shared-key MCP integration. A new
// server URL leaves the connection needing reconnect, as in Onyx.
type fakeIntegrationServer struct {
	mu          sync.Mutex
	integration map[string]any
	failSave    bool
	saves       int
}

func (f *fakeIntegrationServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	path := strings.TrimPrefix(r.URL.Path, "/api")
	var body map[string]any
	_ = json.NewDecoder(r.Body).Decode(&body)
	w.Header().Set("Content-Type", "application/json")
	switch {
	case r.Method == http.MethodPost && path == "/admin/integrations":
		f.integration = map[string]any{
			"id": 1, "kind": "mcp", "enabled": true, "installation_policy": "AVAILABLE",
			"name": body["name"], "auth_mode": body["auth_mode"], "auth_method": body["auth_method"],
			"header_template": body["header_template"], "config": body["config"],
			"organization_status": map[string]any{"state": "not_set_up"},
		}
	case r.Method == http.MethodPatch && path == "/admin/integrations/1":
		if config, ok := body["config"].(map[string]any); ok {
			old, _ := f.integration["config"].(map[string]any)
			if old["server_url"] != config["server_url"] {
				f.integration["organization_status"] = map[string]any{"state": "needs_reconnect"}
			}
		}
		for key, value := range body {
			f.integration[key] = value
		}
	case r.Method == http.MethodPut && path == "/admin/integrations/1/organization-connection":
		if f.failSave {
			w.WriteHeader(http.StatusBadGateway)
			_, _ = w.Write([]byte(`{"error_code": "BAD_GATEWAY", "detail": "unavailable"}`))
			return
		}
		f.saves++
		f.integration["organization_status"] = map[string]any{"state": "connected"}
		_, _ = w.Write([]byte(`null`))
		return
	case r.Method == http.MethodPut && path == "/admin/integrations/1/installation-policy":
		f.integration["installation_policy"] = body["installation_policy"]
		_, _ = w.Write([]byte(`null`))
		return
	case r.Method == http.MethodPost && path == "/admin/integrations/1/actions/refresh",
		r.Method == http.MethodDelete && path == "/admin/integrations/1":
		_, _ = w.Write([]byte(`null`))
		return
	case r.Method == http.MethodGet && path == "/admin/integrations/1":
	default:
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"error_code": "NOT_FOUND", "detail": "not found"}`))
		return
	}
	_ = json.NewEncoder(w).Encode(f.integration)
}

func (f *fakeIntegrationServer) set(failSave bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.failSave = failSave
}

func (f *fakeIntegrationServer) checkSaves(want int) resource.TestCheckFunc {
	return func(_ *terraform.State) error {
		f.mu.Lock()
		defer f.mu.Unlock()
		if f.saves != want {
			return fmt.Errorf("credential saves = %d, want %d", f.saves, want)
		}
		return nil
	}
}

func fakeIntegrationConfig(endpoint, serverURL string) string {
	return fmt.Sprintf(`
provider "onyx" {
  endpoint   = %q
  api_key    = "on_test_key"
  api_prefix = ""
}

resource "onyx_integration" "test" {
  name                                = "retry"
  server_url                          = %q
  auth_mode                           = "shared"
  auth_method                         = "api_key"
  header_template                     = { Authorization = "Bearer {api_key}" }
  organization_credentials_wo         = { api_key = "tf-key" }
  organization_credentials_wo_version = 1
}
`, endpoint, serverURL)
}

// Onyx takes a new server URL, then the key save fails. A refresh reads the new
// URL into the state, so only the pending mark makes the next apply send the key.
func TestIntegrationRetriesCredentialsThatAFailedApplyCouldNotSave(t *testing.T) {
	fake := &fakeIntegrationServer{}
	server := httptest.NewServer(fake)
	t.Cleanup(server.Close)

	resource.UnitTest(t, resource.TestCase{
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: fakeIntegrationConfig(server.URL, "https://mcp.example.com/mcp"),
				Check:  fake.checkSaves(1),
			},
			{
				PreConfig:   func() { fake.set(true) },
				Config:      fakeIntegrationConfig(server.URL, "https://mcp2.example.com/mcp"),
				ExpectError: regexp.MustCompile("Failed to save the Onyx integration organization credentials"),
			},
			{
				PreConfig: func() { fake.set(false) },
				Config:    fakeIntegrationConfig(server.URL, "https://mcp2.example.com/mcp"),
				Check:     fake.checkSaves(2),
			},
		},
	})
}
