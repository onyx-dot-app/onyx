package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/hashicorp/terraform-plugin-testing/helper/acctest"
	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/plancheck"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

const integrationOpenAPIDocument = `{
  "openapi": "3.0.0",
  "info": {"title": "Weather", "version": "1.0.0"},
  "servers": [{"url": "https://api.example.com"}],
  "paths": {"/forecast": {"get": {"operationId": "get_forecast", "summary": "Get the forecast",
    "responses": {"200": {"description": "OK"}}}}}
}`

// testAccIntegrationMCPServer gives a reachable MCP server that takes
// "Bearer <key>", when the environment names one. Without it, the tests use an
// unreachable server and do not check the loaded actions.
func testAccIntegrationMCPServer() (url, apiKey string) {
	url = os.Getenv("ONYX_TF_ACC_MCP_SERVER_URL")
	if url == "" {
		return mcpServerURL, "tf-acc-key"
	}
	return url, os.Getenv("ONYX_TF_ACC_MCP_API_KEY")
}

// Onyx masks a header value with no placeholder on reads.
const integrationLiteralHeader = "literal-team-header-value"

func testAccIntegrationMCPConfig(name, description, policy string, enabled bool, version int) string {
	serverURL, apiKey := testAccIntegrationMCPServer()
	return fmt.Sprintf(`
resource "onyx_integration" "test" {
  name                                = %q
  description                         = %q
  server_url                          = %q
  auth_mode                           = "shared"
  auth_method                         = "api_key"
  header_template                     = { Authorization = "Bearer {api_key}", "X-Team" = %q }
  organization_credentials_wo         = { api_key = %q }
  organization_credentials_wo_version = %d
  installation_policy                 = %q
  enabled                             = %t
}
`, name, description, serverURL, integrationLiteralHeader, apiKey, version, policy, enabled)
}

func TestAccIntegrationResource(t *testing.T) {
	name := acctest.RandomWithPrefix("tf-acc-integration")
	openAPIConfig := fmt.Sprintf(`
resource "onyx_integration" "test" {
  name             = %q
  openapi_document = %q
  auth_mode        = "none"
  header_template  = {}
}
`, name, integrationOpenAPIDocument)

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckIntegrationDestroyed(t),
		Steps: []resource.TestStep{
			{
				// Onyx creates an integration on and AVAILABLE, so a create
				// must send the configured switch and install setting.
				Config: testAccIntegrationMCPConfig(name, "Weather tools", "DEFAULT", false, 1),
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttrSet("onyx_integration.test", "id"),
					resource.TestCheckResourceAttr("onyx_integration.test", "kind", "mcp"),
					resource.TestCheckResourceAttr("onyx_integration.test", "transport", "STREAMABLE_HTTP"),
					resource.TestCheckResourceAttr("onyx_integration.test", "installation_policy", "DEFAULT"),
					resource.TestCheckResourceAttr("onyx_integration.test", "enabled", "false"),
					resource.TestCheckResourceAttr("onyx_integration.test", "header_template.Authorization", "Bearer {api_key}"),
					resource.TestCheckResourceAttr("onyx_integration.test", "header_template.X-Team", integrationLiteralHeader),
					resource.TestCheckNoResourceAttr("onyx_integration.test", "organization_credentials_wo.%"),
				),
			},
			{
				// The switch, the install setting and the credentials use
				// separate routes, so an update must reach each of them.
				Config: testAccIntegrationMCPConfig(name, "Forecasts", "REQUIRED", true, 2),
				ConfigPlanChecks: resource.ConfigPlanChecks{
					PreApply: []plancheck.PlanCheck{
						plancheck.ExpectResourceAction("onyx_integration.test", plancheck.ResourceActionUpdate),
					},
				},
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_integration.test", "description", "Forecasts"),
					resource.TestCheckResourceAttr("onyx_integration.test", "installation_policy", "REQUIRED"),
					resource.TestCheckResourceAttr("onyx_integration.test", "enabled", "true"),
					testAccCheckIntegrationConnected(t, "onyx_integration.test"),
				),
			},
			{
				ResourceName:      "onyx_integration.test",
				ImportState:       true,
				ImportStateVerify: true,
				// Write-only values and their counter never come back from Onyx,
				// and an import has no known value to match the header mask.
				ImportStateVerifyIgnore: []string{"organization_credentials_wo_version", "header_template.X-Team"},
			},
			{
				// Moving to an OpenAPI document changes the shape, which Onyx
				// cannot do in place.
				Config: openAPIConfig,
				ConfigPlanChecks: resource.ConfigPlanChecks{
					PreApply: []plancheck.PlanCheck{
						plancheck.ExpectResourceAction("onyx_integration.test", plancheck.ResourceActionDestroyBeforeCreate),
					},
				},
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_integration.test", "kind", "api"),
					resource.TestCheckNoResourceAttr("onyx_integration.test", "server_url"),
					resource.TestCheckNoResourceAttr("onyx_integration.test", "transport"),
					resource.TestCheckResourceAttr("onyx_integration.test", "header_template.%", "0"),
				),
			},
			{
				ResourceName:            "onyx_integration.test",
				ImportState:             true,
				ImportStateVerify:       true,
				ImportStateVerifyIgnore: []string{"openapi_document", "header_template"},
			},
		},
	})
}

// The imported state holds the stored document, not the configured text.
// That must not read as a change of shape, which would replace the integration.
func TestAccIntegrationResourceImportOpenAPI(t *testing.T) {
	name := acctest.RandomWithPrefix("tf-acc-integration")
	config := fmt.Sprintf(`
resource "onyx_integration" "test" {
  name             = %q
  openapi_document = %q
  auth_mode        = "none"
}
`, name, integrationOpenAPIDocument)
	var id string

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckIntegrationDestroyed(t),
		Steps: []resource.TestStep{
			{
				PreConfig: func() {
					document := integrationOpenAPIDocument
					created, err := testAccClient(t).CreateIntegration(context.Background(), client.IntegrationCreate{
						ForOrganization: true,
						Name:            name,
						AuthMode:        "none",
						Config: client.IntegrationConfig{
							Shape:           client.IntegrationShapeOpenAPI,
							OpenAPIDocument: &document,
						},
					})
					if err != nil {
						t.Fatal(err)
					}
					id = fmt.Sprint(created.ID)
				},
				Config:             config,
				ResourceName:       "onyx_integration.test",
				ImportState:        true,
				ImportStateIdFunc:  func(*terraform.State) (string, error) { return id, nil },
				ImportStatePersist: true,
			},
			{
				Config: config,
				ConfigPlanChecks: resource.ConfigPlanChecks{
					PreApply: []plancheck.PlanCheck{expectNoReplace{address: "onyx_integration.test"}},
				},
			},
		},
	})
}

func testAccCheckIntegrationConnected(t *testing.T, address string) resource.TestCheckFunc {
	return func(state *terraform.State) error {
		rs, ok := state.RootModule().Resources[address]
		if !ok {
			return fmt.Errorf("%s not found in state", address)
		}
		id, err := parseIDString(rs.Primary.ID)
		if err != nil {
			return err
		}
		integration, err := testAccClient(t).GetIntegration(context.Background(), id)
		if err != nil {
			return err
		}
		if status := integration.OrganizationStatus; status == nil || status.State != "connected" {
			return fmt.Errorf("organization status = %+v, want connected", status)
		}
		// Saving the key must also load the server's tools, or chat has none.
		if os.Getenv("ONYX_TF_ACC_MCP_SERVER_URL") == "" {
			return nil
		}
		count, err := testAccIntegrationActionCount(id)
		if err != nil {
			return err
		}
		if count == 0 {
			return fmt.Errorf("integration %d has no actions", id)
		}
		return nil
	}
}

func testAccIntegrationActionCount(id int64) (int, error) {
	url := fmt.Sprintf("%s%s/admin/integrations/%d/actions", testAccServerURL(), testAccAPIPrefix(), id)
	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	req.Header.Set("Authorization", "Bearer "+bootstrapKey)
	resp, err := (&http.Client{Timeout: 30 * time.Second}).Do(req)
	if err != nil {
		return 0, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("GET %s: %s", url, resp.Status)
	}
	var body struct {
		Actions []json.RawMessage `json:"actions"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return 0, err
	}
	return len(body.Actions), nil
}

func testAccCheckIntegrationDestroyed(t *testing.T) resource.TestCheckFunc {
	return func(state *terraform.State) error {
		c := testAccClient(t)
		for name, rs := range state.RootModule().Resources {
			if rs.Type != "onyx_integration" {
				continue
			}
			id, err := parseIDString(rs.Primary.ID)
			if err != nil {
				return err
			}
			if _, err := c.GetIntegration(context.Background(), id); err == nil {
				return fmt.Errorf("%s (id %d) still exists after destroy", name, id)
			} else if !client.IsNotFound(err) {
				return fmt.Errorf("unexpected error reading %s after destroy: %w", name, err)
			}
		}
		return nil
	}
}

// A private integration is published in place by its install setting. Each
// user connects, so Onyx does not call the server on create.
func TestAccIntegrationResourcePrivate(t *testing.T) {
	name := acctest.RandomWithPrefix("tf-acc-integration")
	config := func(policy string) string {
		return fmt.Sprintf(`
resource "onyx_integration" "test" {
  name                = %q
  server_url          = %q
  auth_mode           = "individual"
  auth_method         = "api_key"
  header_template     = { Authorization = "Bearer {api_key}" }
  installation_policy = %q
}
`, name, mcpServerURL, policy)
	}

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckIntegrationDestroyed(t),
		Steps: []resource.TestStep{
			{
				// The resource cannot send OAuth client settings, so Onyx
				// would refuse the integration after the plan.
				Config:      strings.Replace(config("NOT_AVAILABLE"), `"api_key"`, `"oauth2"`, 1),
				ExpectError: regexp.MustCompile(`value must be one of`),
			},
			{
				Config: config("NOT_AVAILABLE"),
				Check:  resource.TestCheckResourceAttr("onyx_integration.test", "installation_policy", "NOT_AVAILABLE"),
			},
			{
				Config: config("AVAILABLE"),
				ConfigPlanChecks: resource.ConfigPlanChecks{
					PreApply: []plancheck.PlanCheck{
						plancheck.ExpectResourceAction("onyx_integration.test", plancheck.ResourceActionUpdate),
					},
				},
				Check: resource.TestCheckResourceAttr("onyx_integration.test", "installation_policy", "AVAILABLE"),
			},
		},
	})
}

type expectNoReplace struct{ address string }

func (e expectNoReplace) CheckPlan(_ context.Context, req plancheck.CheckPlanRequest, resp *plancheck.CheckPlanResponse) {
	for _, change := range req.Plan.ResourceChanges {
		if change.Address == e.address && change.Change.Actions.Replace() {
			resp.Error = fmt.Errorf("%s is planned for replacement", e.address)
		}
	}
}
