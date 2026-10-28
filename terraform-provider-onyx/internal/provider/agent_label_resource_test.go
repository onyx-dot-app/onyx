package provider

import (
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
)

func TestAccAgentLabelResource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_agent_label" "test" {
  name = "tf-acc-label"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttrSet("onyx_agent_label.test", "id"),
					resource.TestCheckResourceAttr("onyx_agent_label.test", "name", "tf-acc-label"),
				),
			},
			{
				ResourceName:      "onyx_agent_label.test",
				ImportState:       true,
				ImportStateVerify: true,
			},
			{
				// A rename keeps the id.
				Config: `
resource "onyx_agent_label" "test" {
  name = "tf-acc-label-renamed"
}
`,
				Check: resource.TestCheckResourceAttr("onyx_agent_label.test", "name", "tf-acc-label-renamed"),
			},
		},
	})
}
