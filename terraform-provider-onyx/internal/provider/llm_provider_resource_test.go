package provider

import (
	"context"
	"fmt"
	"strconv"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

func TestAccLLMProviderResource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckLLMProviderDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_llm_provider" "test" {
  name          = "tf-acc-openai"
  provider_type = "openai"
  api_key       = "sk-tf-acc-fake-key"

  model_configurations = [
    { name = "gpt-5-mini" },
  ]
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttrSet("onyx_llm_provider.test", "id"),
					resource.TestCheckResourceAttr("onyx_llm_provider.test", "name", "tf-acc-openai"),
					resource.TestCheckResourceAttr("onyx_llm_provider.test", "provider_type", "openai"),
					resource.TestCheckResourceAttr("onyx_llm_provider.test", "is_public", "true"),
					resource.TestCheckResourceAttr("onyx_llm_provider.test", "is_auto_mode", "false"),
					resource.TestCheckResourceAttr("onyx_llm_provider.test", "model_configurations.#", "1"),
					// The configured secret must live in state untouched by the
					// masked read-back.
					resource.TestCheckResourceAttr("onyx_llm_provider.test", "api_key", "sk-tf-acc-fake-key"),
				),
			},
			{
				ResourceName:      "onyx_llm_provider.test",
				ImportState:       true,
				ImportStateVerify: true,
				// api_key is masked on read so the imported state has it null.
				// model_configurations differ per-field after import: the API
				// enriches models with computed values (max tokens, display
				// name) that deliberately aren't refreshed into managed state.
				// force_delete is provider-side only and unknowable on import.
				ImportStateVerifyIgnore: []string{"api_key", "model_configurations", "force_delete"},
			},
			{
				Config: `
resource "onyx_llm_provider" "test" {
  name          = "tf-acc-openai-renamed"
  provider_type = "openai"
  api_key       = "sk-tf-acc-fake-key-rotated"

  model_configurations = [
    { name = "gpt-5-mini" },
    {
      name                = "gpt-5-nano"
      is_visible          = false
      custom_display_name = "Cheap GPT-5"
    },
  ]
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_llm_provider.test", "name", "tf-acc-openai-renamed"),
					resource.TestCheckResourceAttr("onyx_llm_provider.test", "model_configurations.#", "2"),
					resource.TestCheckResourceAttr("onyx_llm_provider.test", "api_key", "sk-tf-acc-fake-key-rotated"),
					testAccCheckLLMProviderModelNames(t, "onyx_llm_provider.test", []string{"gpt-5-mini", "gpt-5-nano"}),
				),
			},
			{
				// Shrinking the model list must delete the removed model
				// server-side (full replace-by-name).
				Config: `
resource "onyx_llm_provider" "test" {
  name          = "tf-acc-openai-renamed"
  provider_type = "openai"
  api_key       = "sk-tf-acc-fake-key-rotated"

  model_configurations = [
    { name = "gpt-5-mini" },
  ]
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_llm_provider.test", "model_configurations.#", "1"),
					testAccCheckLLMProviderModelNames(t, "onyx_llm_provider.test", []string{"gpt-5-mini"}),
				),
			},
		},
	})
}

// testAccCheckLLMProviderModelNames asserts the server-side model list for the
// resource's provider id matches exactly the given names.
func testAccCheckLLMProviderModelNames(t *testing.T, resourceName string, want []string) resource.TestCheckFunc {
	return func(s *terraform.State) error {
		rs, ok := s.RootModule().Resources[resourceName]
		if !ok {
			return fmt.Errorf("resource %s not found in state", resourceName)
		}
		id, err := strconv.ParseInt(rs.Primary.ID, 10, 64)
		if err != nil {
			return fmt.Errorf("malformed id %q", rs.Primary.ID)
		}
		view, err := testAccClient(t).GetLLMProvider(context.Background(), id)
		if err != nil {
			return err
		}
		remote := map[string]bool{}
		for _, mc := range view.ModelConfigurations {
			remote[mc.Name] = true
		}
		if len(remote) != len(want) {
			return fmt.Errorf("server has %d models %v, want %d %v", len(remote), remote, len(want), want)
		}
		for _, name := range want {
			if !remote[name] {
				return fmt.Errorf("model %q missing server-side; have %v", name, remote)
			}
		}
		return nil
	}
}

func testAccCheckLLMProviderDestroyed(t *testing.T) resource.TestCheckFunc {
	return func(s *terraform.State) error {
		c := testAccClient(t)
		for name, rs := range s.RootModule().Resources {
			if rs.Type != "onyx_llm_provider" {
				continue
			}
			id, err := strconv.ParseInt(rs.Primary.ID, 10, 64)
			if err != nil {
				return fmt.Errorf("%s: malformed id %q", name, rs.Primary.ID)
			}
			if _, err := c.GetLLMProvider(context.Background(), id); !client.IsNotFound(err) {
				return fmt.Errorf("%s: LLM provider %d still exists after destroy (err: %v)", name, id, err)
			}
		}
		return nil
	}
}
