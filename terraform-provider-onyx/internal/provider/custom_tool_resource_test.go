package provider

import (
	"context"
	"fmt"
	"regexp"
	"strconv"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

// A definition Onyx accepts: it needs info.title, info.description, a server
// URL, and an operationId plus a summary on every operation.
const customToolDefinition = `jsonencode({
    openapi = "3.0.0"
    info = {
      title       = "Weather"
      description = "Looks up the weather"
    }
    servers = [{ url = "https://api.example.com" }]
    paths = {
      "/weather" = {
        get = {
          operationId = "getWeather"
          summary     = "Get the current weather"
          responses   = { "200" = { description = "ok" } }
        }
      }
    }
  })`

const customToolDefinitionUpdated = `jsonencode({
    openapi = "3.0.0"
    info = {
      title       = "Weather"
      description = "Looks up the weather and the forecast"
    }
    servers = [{ url = "https://api.example.com" }]
    paths = {
      "/weather" = {
        get = {
          operationId = "getWeather"
          summary     = "Get the current weather"
          responses   = { "200" = { description = "ok" } }
        }
      }
      "/forecast" = {
        get = {
          operationId = "getForecast"
          summary     = "Get the forecast"
          responses   = { "200" = { description = "ok" } }
        }
      }
    }
  })`

func TestAccCustomToolResource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckCustomToolDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_custom_tool" "test" {
  name        = "tf-acc-weather"
  description = "Looks up the weather"
  definition  = ` + customToolDefinition + `

  custom_headers = {
    "X-Api-Key" = "tf-acc-secret"
  }
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_custom_tool.test", "name", "tf-acc-weather"),
					resource.TestCheckResourceAttr("onyx_custom_tool.test", "description", "Looks up the weather"),
					resource.TestCheckResourceAttr("onyx_custom_tool.test", "passthrough_auth", "false"),
					resource.TestCheckResourceAttr("onyx_custom_tool.test", "enabled", "true"),
					resource.TestCheckResourceAttr("onyx_custom_tool.test", "custom_headers.X-Api-Key", "tf-acc-secret"),
					resource.TestCheckResourceAttrSet("onyx_custom_tool.test", "id"),
					resource.TestCheckResourceAttrSet("onyx_custom_tool.test", "display_name"),
					resource.TestCheckNoResourceAttr("onyx_custom_tool.test", "oauth_config_id"),
				),
			},
			{
				// A full-replace update: rename, change the definition, drop
				// the headers, and disable the action. Dropping the headers
				// only works because the write sends an empty list rather than
				// null, which the server reads as "leave them alone".
				Config: `
resource "onyx_custom_tool" "test" {
  name       = "tf-acc-weather-renamed"
  definition = ` + customToolDefinitionUpdated + `
  enabled    = false
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_custom_tool.test", "name", "tf-acc-weather-renamed"),
					resource.TestCheckResourceAttr("onyx_custom_tool.test", "description", ""),
					resource.TestCheckResourceAttr("onyx_custom_tool.test", "enabled", "false"),
					resource.TestCheckNoResourceAttr("onyx_custom_tool.test", "custom_headers.%"),
				),
			},
			{
				ResourceName:      "onyx_custom_tool.test",
				ImportState:       true,
				ImportStateVerify: true,
			},
		},
	})
}

// Onyx rejects a definition it cannot turn into callable methods, and the
// provider asks it during planning rather than at apply time.
func TestAccCustomToolResourceRejectsABadDefinition(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_custom_tool" "bad" {
  name       = "tf-acc-bad-definition"
  definition = jsonencode({ openapi = "3.0.0" })
}
`,
				ExpectError: regexp.MustCompile(`(?s)Onyx rejected the action definition`),
			},
		},
	})
}

// passthrough_auth and a fixed Authorization header are mutually exclusive.
// The provider says so while planning; the server would answer 400.
func TestAccCustomToolResourceRejectsConflictingAuth(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_custom_tool" "conflict" {
  name             = "tf-acc-conflicting-auth"
  definition       = ` + customToolDefinition + `
  passthrough_auth = true

  custom_headers = {
    "Authorization" = "Bearer nope"
  }
}
`,
				ExpectError: regexp.MustCompile(`(?s)Conflicting authentication settings`),
			},
		},
	})
}

func testAccCheckCustomToolDestroyed(t *testing.T) resource.TestCheckFunc {
	return func(state *terraform.State) error {
		c := testAccClient(t)
		for name, rs := range state.RootModule().Resources {
			if rs.Type != "onyx_custom_tool" {
				continue
			}
			id, err := parseIDString(rs.Primary.ID)
			if err != nil {
				return err
			}
			if _, err := c.GetCustomTool(context.Background(), id); err == nil {
				return fmt.Errorf("%s (id %d) still exists after destroy", name, id)
			} else if !client.IsNotFound(err) {
				return fmt.Errorf("unexpected error reading %s after destroy: %w", name, err)
			}
		}
		return nil
	}
}

// Onyx answers the read endpoint for built-in actions but refuses every write
// to them, so importing one would record state that can neither be updated nor
// destroyed. The refresh rejects it instead.
func TestAccCustomToolResourceRejectsImportingABuiltIn(t *testing.T) {
	testAccPreCheck(t)

	tools, err := testAccClient(t).ListTools(context.Background())
	if err != nil {
		t.Fatalf("failed to list actions: %v", err)
	}
	builtInID := ""
	for _, tool := range tools {
		if tool.InCodeToolID != nil {
			builtInID = strconv.FormatInt(tool.ID, 10)
			break
		}
	}
	if builtInID == "" {
		t.Skip("this deployment exposes no built-in actions")
	}

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_custom_tool" "builtin" {
  name       = "tf-acc-import-target"
  definition = ` + customToolDefinition + `
}
`,
				ResourceName:  "onyx_custom_tool.builtin",
				ImportState:   true,
				ImportStateId: builtInID,
				ExpectError:   regexp.MustCompile(`(?s)Not a custom Onyx action`),
			},
		},
	})
}
