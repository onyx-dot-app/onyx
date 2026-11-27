package provider

import (
	"context"
	"fmt"
	"testing"

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

func testAccIntegrationMCPConfig(name, description, policy string, enabled bool, version int) string {
	return fmt.Sprintf(`
resource "onyx_integration" "test" {
  name                                = %q
  description                         = %q
  server_url                          = %q
  auth_mode                           = "shared"
  auth_method                         = "api_key"
  header_template                     = { Authorization = "Bearer {api_key}" }
  organization_credentials_wo         = { api_key = "tf-acc-key-%d" }
  organization_credentials_wo_version = %d
  installation_policy                 = %q
  enabled                             = %t
}
`, name, description, mcpServerURL, version, version, policy, enabled)
}

func TestAccIntegrationResource(t *testing.T) {
	name := acctest.RandomWithPrefix("tf-acc-integration")

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckIntegrationDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: testAccIntegrationMCPConfig(name, "Weather tools", "AVAILABLE", true, 1),
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttrSet("onyx_integration.test", "id"),
					resource.TestCheckResourceAttr("onyx_integration.test", "kind", "mcp"),
					resource.TestCheckResourceAttr("onyx_integration.test", "transport", "STREAMABLE_HTTP"),
					resource.TestCheckResourceAttr("onyx_integration.test", "installation_policy", "AVAILABLE"),
					resource.TestCheckResourceAttr("onyx_integration.test", "enabled", "true"),
					resource.TestCheckResourceAttr("onyx_integration.test", "header_template.Authorization", "Bearer {api_key}"),
					resource.TestCheckNoResourceAttr("onyx_integration.test", "organization_credentials_wo.%"),
				),
			},
			{
				// The switch, the install setting and the credentials use
				// separate routes, so an update must reach each of them.
				Config: testAccIntegrationMCPConfig(name, "Forecasts", "REQUIRED", false, 2),
				ConfigPlanChecks: resource.ConfigPlanChecks{
					PreApply: []plancheck.PlanCheck{
						plancheck.ExpectResourceAction("onyx_integration.test", plancheck.ResourceActionUpdate),
					},
				},
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_integration.test", "description", "Forecasts"),
					resource.TestCheckResourceAttr("onyx_integration.test", "installation_policy", "REQUIRED"),
					resource.TestCheckResourceAttr("onyx_integration.test", "enabled", "false"),
					testAccCheckIntegrationConnected(t, "onyx_integration.test"),
				),
			},
			{
				ResourceName:      "onyx_integration.test",
				ImportState:       true,
				ImportStateVerify: true,
				// Write-only values and their counter never come back from Onyx.
				ImportStateVerifyIgnore: []string{"organization_credentials_wo_version"},
			},
			{
				// Moving to an OpenAPI document changes the shape, which Onyx
				// cannot do in place.
				Config: fmt.Sprintf(`
resource "onyx_integration" "test" {
  name             = %q
  openapi_document = %q
  auth_mode        = "none"
}
`, name, integrationOpenAPIDocument),
				ConfigPlanChecks: resource.ConfigPlanChecks{
					PreApply: []plancheck.PlanCheck{
						plancheck.ExpectResourceAction("onyx_integration.test", plancheck.ResourceActionDestroyBeforeCreate),
					},
				},
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_integration.test", "kind", "api"),
					resource.TestCheckNoResourceAttr("onyx_integration.test", "server_url"),
					resource.TestCheckNoResourceAttr("onyx_integration.test", "transport"),
					resource.TestCheckNoResourceAttr("onyx_integration.test", "header_template.%"),
				),
			},
			{
				ResourceName:            "onyx_integration.test",
				ImportState:             true,
				ImportStateVerify:       true,
				ImportStateVerifyIgnore: []string{"openapi_document"},
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
		return nil
	}
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
