package provider

import (
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
)

func TestAccLLMProvidersDataSource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				// Create a provider in the same config so at least one row is
				// guaranteed to exist.
				Config: `
resource "onyx_llm_provider" "ds_seed" {
  name          = "tf-acc-ds-seed"
  provider_type = "openai"
  api_key       = "sk-tf-acc-fake-key"

  model_configurations = [
    { name = "gpt-5-mini" },
  ]
}

data "onyx_llm_providers" "all" {
  depends_on = [onyx_llm_provider.ds_seed]
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttrSet("data.onyx_llm_providers.all", "providers.#"),
					resource.TestCheckResourceAttrSet("data.onyx_llm_providers.all", "providers.0.id"),
					resource.TestCheckResourceAttrSet("data.onyx_llm_providers.all", "providers.0.provider_type"),
				),
			},
		},
	})
}

func TestAccSettingsDataSource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: `data "onyx_settings" "current" {}`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttrSet("data.onyx_settings.current", "tier"),
					resource.TestCheckResourceAttrSet("data.onyx_settings.current", "application_status"),
				),
			},
		},
	})
}

func TestAccEmbeddingProvidersDataSource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_embedding_provider" "ds_seed" {
  provider_type = "voyage"
  api_key       = "pa-tf-acc-fake-key"
}

data "onyx_embedding_providers" "all" {
  depends_on = [onyx_embedding_provider.ds_seed]
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttrSet("data.onyx_embedding_providers.all", "providers.#"),
				),
			},
		},
	})
}
