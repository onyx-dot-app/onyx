package provider

import (
	"context"
	"fmt"
	"strconv"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
)

func TestAccLLMProviderDefaultResource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				// force_delete is required on the provider: at destroy time it
				// holds the deployment default (deletes are ordered after the
				// default resource's no-op destroy).
				Config: `
resource "onyx_llm_provider" "for_default" {
  name          = "tf-acc-default-holder"
  provider_type = "openai"
  api_key       = "sk-tf-acc-fake-key"
  force_delete  = true

  model_configurations = [
    { name = "gpt-5-mini" },
    { name = "gpt-5-nano" },
  ]
}

resource "onyx_llm_provider_default" "test" {
  provider_id = onyx_llm_provider.for_default.id
  model_name  = "gpt-5-mini"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_llm_provider_default.test", "id", "default"),
					resource.TestCheckResourceAttrPair(
						"onyx_llm_provider_default.test", "provider_id",
						"onyx_llm_provider.for_default", "id",
					),
					resource.TestCheckResourceAttr("onyx_llm_provider_default.test", "model_name", "gpt-5-mini"),
					testAccCheckServerDefaultModel(t, "onyx_llm_provider.for_default", "gpt-5-mini"),
				),
			},
			{
				Config: `
resource "onyx_llm_provider" "for_default" {
  name          = "tf-acc-default-holder"
  provider_type = "openai"
  api_key       = "sk-tf-acc-fake-key"
  force_delete  = true

  model_configurations = [
    { name = "gpt-5-mini" },
    { name = "gpt-5-nano" },
  ]
}

resource "onyx_llm_provider_default" "test" {
  provider_id = onyx_llm_provider.for_default.id
  model_name  = "gpt-5-nano"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_llm_provider_default.test", "model_name", "gpt-5-nano"),
					testAccCheckServerDefaultModel(t, "onyx_llm_provider.for_default", "gpt-5-nano"),
				),
			},
			{
				ResourceName:      "onyx_llm_provider_default.test",
				ImportState:       true,
				ImportStateId:     "default",
				ImportStateVerify: true,
			},
		},
	})
}

// testAccCheckServerDefaultModel asserts the deployment default points at the
// given resource's provider id and model name.
func testAccCheckServerDefaultModel(t *testing.T, providerResourceName, wantModel string) resource.TestCheckFunc {
	return func(s *terraform.State) error {
		rs, ok := s.RootModule().Resources[providerResourceName]
		if !ok {
			return fmt.Errorf("resource %s not found in state", providerResourceName)
		}
		wantProviderID, err := strconv.ParseInt(rs.Primary.ID, 10, 64)
		if err != nil {
			return fmt.Errorf("malformed provider id %q", rs.Primary.ID)
		}
		list, err := testAccClient(t).ListLLMProviders(context.Background())
		if err != nil {
			return err
		}
		if list.DefaultText == nil {
			return fmt.Errorf("no deployment default model is set")
		}
		if list.DefaultText.ProviderID != wantProviderID || list.DefaultText.ModelName != wantModel {
			return fmt.Errorf("deployment default is provider %d model %q, want provider %d model %q",
				list.DefaultText.ProviderID, list.DefaultText.ModelName, wantProviderID, wantModel)
		}
		return nil
	}
}
