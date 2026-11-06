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
				// force_delete: at destroy time this provider still holds the
				// deployment default.
				Config: `
resource "onyx_llm_provider" "for_default" {
  name          = "tf-acc-default-holder"
  provider_type = "openai"
  api_key       = "sk-tf-acc-fake-key"
  force_delete  = true

  model_configurations = [
    { name = "gpt-6-luna" },
    { name = "gpt-6-sol" },
  ]
}

resource "onyx_llm_provider_default" "test" {
  provider_id = onyx_llm_provider.for_default.id
  model_name  = "gpt-6-luna"

  craft_provider_id = onyx_llm_provider.for_default.id
  craft_model_name  = "gpt-6-sol"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_llm_provider_default.test", "craft_model_name", "gpt-6-sol"),
					testAccCheckServerCraftDefault(t, "gpt-6-sol"),
					resource.TestCheckResourceAttr("onyx_llm_provider_default.test", "id", "default"),
					resource.TestCheckResourceAttrPair(
						"onyx_llm_provider_default.test", "provider_id",
						"onyx_llm_provider.for_default", "id",
					),
					resource.TestCheckResourceAttr("onyx_llm_provider_default.test", "model_name", "gpt-6-luna"),
					testAccCheckServerDefaultModel(t, "onyx_llm_provider.for_default", "gpt-6-luna"),
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
    { name = "gpt-6-luna" },
    { name = "gpt-6-sol" },
  ]
}

resource "onyx_llm_provider_default" "test" {
  provider_id = onyx_llm_provider.for_default.id
  model_name  = "gpt-6-sol"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					// Removing the managed Craft pair clears the server value.
					resource.TestCheckNoResourceAttr("onyx_llm_provider_default.test", "craft_model_name"),
					testAccCheckServerCraftDefault(t, ""),
					resource.TestCheckResourceAttr("onyx_llm_provider_default.test", "model_name", "gpt-6-sol"),
					testAccCheckServerDefaultModel(t, "onyx_llm_provider.for_default", "gpt-6-sol"),
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

// testAccCheckServerCraftDefault asserts the Craft default model name. An
// empty wantModel asserts that no Craft default is set.
func testAccCheckServerCraftDefault(t *testing.T, wantModel string) resource.TestCheckFunc {
	return func(_ *terraform.State) error {
		list, err := testAccClient(t).ListLLMProviders(context.Background())
		if err != nil {
			return err
		}
		switch {
		case wantModel == "" && list.DefaultCraft != nil:
			return fmt.Errorf("want no Craft default, got %q", list.DefaultCraft.ModelName)
		case wantModel != "" && list.DefaultCraft == nil:
			return fmt.Errorf("want Craft default %q, got none", wantModel)
		case wantModel != "" && list.DefaultCraft.ModelName != wantModel:
			return fmt.Errorf("want Craft default %q, got %q", wantModel, list.DefaultCraft.ModelName)
		}
		return nil
	}
}
