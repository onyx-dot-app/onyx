package provider

import (
	"context"
	"fmt"
	"regexp"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
)

// An action for the agent to hold, so tool_ids is exercised against a real id
// rather than a literal.
const personaDependencies = `
resource "onyx_custom_tool" "persona" {
  name       = "tf-acc-persona-action"
  definition = jsonencode({
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
  })
}
`

func TestAccPersonaResource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckPersonaDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: personaDependencies + `
resource "onyx_persona" "test" {
  name          = "tf-acc-agent"
  description   = "Answers support questions"
  system_prompt = "You are a support agent. Be brief."
  task_prompt   = "Answer using the handbook."
  tool_ids      = [onyx_custom_tool.persona.id]
  is_listed     = false

  starter_messages = [
    {
      name    = "Refunds"
      message = "How do refunds work?"
    },
    {
      name    = "Shipping"
      message = "How long does shipping take?"
    },
  ]
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_persona.test", "name", "tf-acc-agent"),
					resource.TestCheckResourceAttr("onyx_persona.test", "description", "Answers support questions"),
					resource.TestCheckResourceAttr("onyx_persona.test", "system_prompt", "You are a support agent. Be brief."),
					resource.TestCheckResourceAttr("onyx_persona.test", "task_prompt", "Answer using the handbook."),
					resource.TestCheckResourceAttr("onyx_persona.test", "is_public", "true"),
					// A new agent is always listed, so this proves the
					// follow-up call to the listed endpoint ran.
					resource.TestCheckResourceAttr("onyx_persona.test", "is_listed", "false"),
					resource.TestCheckResourceAttr("onyx_persona.test", "is_featured", "false"),
					resource.TestCheckResourceAttr("onyx_persona.test", "builtin_persona", "false"),
					resource.TestCheckResourceAttr("onyx_persona.test", "tool_ids.#", "1"),
					resource.TestCheckResourceAttr("onyx_persona.test", "starter_messages.#", "2"),
					resource.TestCheckResourceAttr("onyx_persona.test", "starter_messages.0.name", "Refunds"),
					resource.TestCheckResourceAttrSet("onyx_persona.test", "id"),
					// Optional collections left unset must stay null, or every
					// plan would report a change back to null.
					resource.TestCheckNoResourceAttr("onyx_persona.test", "document_set_ids.#"),
					resource.TestCheckNoResourceAttr("onyx_persona.test", "users.#"),
					resource.TestCheckNoResourceAttr("onyx_persona.test", "groups.#"),
					resource.TestCheckNoResourceAttr("onyx_persona.test", "icon_name"),
				),
			},
			{
				// A full-replace update: rename, drop the description and the
				// task prompt, detach the action, drop the starter messages,
				// and list it again.
				Config: personaDependencies + `
resource "onyx_persona" "test" {
  name          = "tf-acc-agent-renamed"
  system_prompt = "You are a support agent. Be thorough."
  tool_ids      = []
  is_listed     = true
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_persona.test", "name", "tf-acc-agent-renamed"),
					resource.TestCheckResourceAttr("onyx_persona.test", "description", ""),
					resource.TestCheckResourceAttr("onyx_persona.test", "system_prompt", "You are a support agent. Be thorough."),
					resource.TestCheckResourceAttr("onyx_persona.test", "task_prompt", ""),
					resource.TestCheckResourceAttr("onyx_persona.test", "is_listed", "true"),
					resource.TestCheckResourceAttr("onyx_persona.test", "tool_ids.#", "0"),
					resource.TestCheckResourceAttr("onyx_persona.test", "starter_messages.#", "0"),
				),
			},
			{
				ResourceName:      "onyx_persona.test",
				ImportState:       true,
				ImportStateVerify: true,
			},
		},
	})
}

// Agent names are unique, and a create that lands on a live name is refused
// rather than quietly taking the agent over.
func TestAccPersonaResourceRejectsADuplicateName(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckPersonaDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_persona" "first" {
  name = "tf-acc-duplicate-name"
}
`,
			},
			{
				Config: `
resource "onyx_persona" "first" {
  name = "tf-acc-duplicate-name"
}

resource "onyx_persona" "second" {
  name = "tf-acc-duplicate-name"
}
`,
				ExpectError: regexp.MustCompile(`(?s)already exists`),
			},
		},
	})
}

func testAccCheckPersonaDestroyed(t *testing.T) resource.TestCheckFunc {
	return func(state *terraform.State) error {
		c := testAccClient(t)
		for name, rs := range state.RootModule().Resources {
			if rs.Type != "onyx_persona" {
				continue
			}
			id, err := parseIDString(rs.Primary.ID)
			if err != nil {
				return err
			}
			_, found, err := c.LookupPersona(context.Background(), id)
			if err != nil {
				return fmt.Errorf("unexpected error reading %s after destroy: %w", name, err)
			}
			if found {
				return fmt.Errorf("%s (id %d) still exists after destroy", name, id)
			}
		}
		return nil
	}
}
