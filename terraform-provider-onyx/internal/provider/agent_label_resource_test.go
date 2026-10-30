package provider

import (
	"fmt"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
)

func TestAccAgentLabelResource(t *testing.T) {
	var firstID string
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
					testAccCaptureAttr("onyx_agent_label.test", "id", &firstID),
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
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_agent_label.test", "name", "tf-acc-label-renamed"),
					func(s *terraform.State) error {
						var id string
						if err := testAccCaptureAttr("onyx_agent_label.test", "id", &id)(s); err != nil {
							return err
						}
						if id != firstID {
							return fmt.Errorf("rename replaced the label: id %s, want %s", id, firstID)
						}
						return nil
					},
				),
			},
		},
	})
}

// testAccCaptureAttr copies one attribute of a resource in state into dst.
func testAccCaptureAttr(name, key string, dst *string) resource.TestCheckFunc {
	return func(s *terraform.State) error {
		rs, ok := s.RootModule().Resources[name]
		if !ok {
			return fmt.Errorf("%s not found in state", name)
		}
		*dst = rs.Primary.Attributes[key]
		return nil
	}
}
