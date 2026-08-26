package provider

import (
	"context"
	"fmt"
	"regexp"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/acctest"
	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

// The URL never has to answer: creating a server is a database write and a
// structural URL check, with no call to the server itself. It does have to look
// external, because Onyx refuses loopback whatever the SSRF setting.
const mcpServerURL = "https://mcp.example.com/mcp"

func TestAccMCPServerResource(t *testing.T) {
	// Onyx does not require server names to be unique, so this is for legible
	// assertions and tidy leftovers rather than to avoid a collision.
	name := acctest.RandomWithPrefix("tf-acc-mcp")

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckMCPServerDestroyed(t),
		Steps: []resource.TestStep{
			{
				// available_in_craft is true from the start: the upsert cannot
				// carry it, so this proves the follow-up PATCH runs on create.
				Config: fmt.Sprintf(`
resource "onyx_mcp_server" "test" {
  name               = %q
  description        = "Weather tools"
  server_url         = %q
  available_in_craft = true
}
`, name, mcpServerURL),
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "name", name),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "description", "Weather tools"),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "server_url", mcpServerURL),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "auth_type", "NONE"),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "auth_performer", "ADMIN"),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "transport", "STREAMABLE_HTTP"),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "is_public", "true"),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "available_in_craft", "true"),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "status", "CREATED"),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "tool_count", "0"),
					resource.TestCheckResourceAttrSet("onyx_mcp_server.test", "id"),
					resource.TestCheckResourceAttrSet("onyx_mcp_server.test", "owner"),
					// A server with no auth has no header template, and unset
					// collections must stay unset or every plan reports a change.
					resource.TestCheckNoResourceAttr("onyx_mcp_server.test", "auth_template_headers.%"),
					resource.TestCheckNoResourceAttr("onyx_mcp_server.test", "groups.#"),
					resource.TestCheckNoResourceAttr("onyx_mcp_server.test", "users.#"),
				),
			},
			{
				// Rename, drop the description, and turn both flags around.
				// Dropping the description is the real test: Onyx preserves the
				// stored one unless an empty string is sent.
				Config: fmt.Sprintf(`
resource "onyx_mcp_server" "test" {
  name               = "%s-renamed"
  server_url         = "https://mcp2.example.com/mcp"
  transport          = "SSE"
  is_public          = false
  available_in_craft = false
}
`, name),
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "name", name+"-renamed"),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "description", ""),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "server_url", "https://mcp2.example.com/mcp"),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "transport", "SSE"),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "is_public", "false"),
					resource.TestCheckResourceAttr("onyx_mcp_server.test", "available_in_craft", "false"),
				),
			},
			{
				ResourceName:      "onyx_mcp_server.test",
				ImportState:       true,
				ImportStateVerify: true,
			},
		},
	})
}

// A shared API token is write-only: Onyx returns it masked, so Terraform holds
// the only true copy. The lifecycle that matters is create, leave alone, rotate.
func TestAccMCPServerResourceAPIToken(t *testing.T) {
	name := acctest.RandomWithPrefix("tf-acc-mcp-token")

	config := func(description, token string) string {
		return fmt.Sprintf(`
resource "onyx_mcp_server" "token" {
  name           = %q
  description    = %q
  server_url     = %q
  auth_type      = "API_TOKEN"
  auth_performer = "ADMIN"
  api_token      = %q
}
`, name, description, mcpServerURL, token)
	}

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckMCPServerDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: config("first", "token-one"),
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_mcp_server.token", "auth_type", "API_TOKEN"),
					resource.TestCheckResourceAttr("onyx_mcp_server.token", "api_token", "token-one"),
					// Onyx writes the header template itself for a shared token.
					resource.TestCheckResourceAttr("onyx_mcp_server.token", "auth_template_headers.Authorization", "Bearer {api_key}"),
				),
			},
			{
				// The token is untouched here. The apply has to leave the stored
				// one alone, and the plan that follows has to come out empty.
				Config: config("second", "token-one"),
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_mcp_server.token", "description", "second"),
					resource.TestCheckResourceAttr("onyx_mcp_server.token", "api_token", "token-one"),
					testAccCheckMCPServerHasStoredCredentials(t, "onyx_mcp_server.token"),
				),
			},
			{
				Config: config("second", "token-two"),
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_mcp_server.token", "api_token", "token-two"),
					testAccCheckMCPServerHasStoredCredentials(t, "onyx_mcp_server.token"),
				),
			},
			{
				ResourceName:      "onyx_mcp_server.token",
				ImportState:       true,
				ImportStateVerify: true,
				// Onyx returns the token masked, so an imported server carries
				// none and the configured value cannot be verified against it.
				ImportStateVerifyIgnore: []string{"api_token"},
			},
		},
	})
}

// OAuth needs a browser, so the configuration is refused while the plan is
// built rather than part-way through an apply.
func TestAccMCPServerResourceRejectsOAuth(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: fmt.Sprintf(`
resource "onyx_mcp_server" "oauth" {
  name       = "tf-acc-mcp-oauth"
  server_url = %q
  auth_type  = "OAUTH"
}
`, mcpServerURL),
				ExpectError: regexp.MustCompile(`(?s)cannot be managed by Terraform`),
			},
		},
	})
}

// A shared token needs api_token, and the missing one is reported before
// anything is created.
func TestAccMCPServerResourceRequiresATokenForSharedAuth(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: fmt.Sprintf(`
resource "onyx_mcp_server" "missing" {
  name       = "tf-acc-mcp-missing-token"
  server_url = %q
  auth_type  = "API_TOKEN"
}
`, mcpServerURL),
				ExpectError: regexp.MustCompile(`(?s)Missing api_token`),
			},
		},
	})
}

// testAccCheckMCPServerHasStoredCredentials proves the server still holds a
// token. The value reads back masked, so its presence is all that can be
// checked from outside — but a token dropped by an update would show up here.
func testAccCheckMCPServerHasStoredCredentials(t *testing.T, name string) resource.TestCheckFunc {
	return func(state *terraform.State) error {
		rs, ok := state.RootModule().Resources[name]
		if !ok {
			return fmt.Errorf("%s is not in state", name)
		}
		id, err := parseIDString(rs.Primary.ID)
		if err != nil {
			return err
		}
		remote, err := testAccClient(t).GetMCPServer(context.Background(), id)
		if err != nil {
			return fmt.Errorf("reading %s back: %w", name, err)
		}
		if remote.AuthType == nil || *remote.AuthType != client.MCPAuthAPIToken {
			return fmt.Errorf("%s no longer authenticates with a token: %+v", name, remote.AuthType)
		}
		if remote.AuthTemplate == nil || len(remote.AuthTemplate.Headers) == 0 {
			return fmt.Errorf("%s lost its header template, so the stored token went with it", name)
		}
		return nil
	}
}

func testAccCheckMCPServerDestroyed(t *testing.T) resource.TestCheckFunc {
	return func(state *terraform.State) error {
		c := testAccClient(t)
		for name, rs := range state.RootModule().Resources {
			if rs.Type != "onyx_mcp_server" {
				continue
			}
			id, err := parseIDString(rs.Primary.ID)
			if err != nil {
				return err
			}
			// The delete is real, so the id must answer 404 rather than come
			// back as a tombstone.
			if _, err := c.GetMCPServer(context.Background(), id); err == nil {
				return fmt.Errorf("%s (id %d) still exists after destroy", name, id)
			} else if !client.IsNotFound(err) {
				return fmt.Errorf("unexpected error reading %s after destroy: %w", name, err)
			}
		}
		return nil
	}
}
