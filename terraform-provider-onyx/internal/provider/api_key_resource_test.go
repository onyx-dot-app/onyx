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

func TestAccAPIKeyResource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckAPIKeyDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_api_key" "test" {
  name = "tf-acc-test-key"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttrSet("onyx_api_key.test", "id"),
					resource.TestCheckResourceAttr("onyx_api_key.test", "name", "tf-acc-test-key"),
					resource.TestCheckResourceAttrSet("onyx_api_key.test", "api_key"),
					resource.TestCheckResourceAttrSet("onyx_api_key.test", "api_key_display"),
					resource.TestCheckResourceAttrSet("onyx_api_key.test", "user_id"),
				),
			},
			{
				ResourceName:      "onyx_api_key.test",
				ImportState:       true,
				ImportStateVerify: true,
				// plaintext key is write-once and never re-read, so import leaves it null
				ImportStateVerifyIgnore: []string{"api_key"},
			},
			{
				Config: `
resource "onyx_api_key" "test" {
  name = "tf-acc-test-key-renamed"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_api_key.test", "name", "tf-acc-test-key-renamed"),
					// In-place update: key material must survive a name change.
					resource.TestCheckResourceAttrSet("onyx_api_key.test", "api_key"),
				),
			},
		},
	})
}

func testAccCheckAPIKeyDestroyed(t *testing.T) resource.TestCheckFunc {
	return func(s *terraform.State) error {
		c := testAccClient(t)
		for name, rs := range s.RootModule().Resources {
			if rs.Type != "onyx_api_key" {
				continue
			}
			id, err := strconv.ParseInt(rs.Primary.ID, 10, 64)
			if err != nil {
				return fmt.Errorf("%s: malformed id %q", name, rs.Primary.ID)
			}
			if _, err := c.GetAPIKey(context.Background(), id); !client.IsNotFound(err) {
				return fmt.Errorf("%s: API key %d still exists after destroy (err: %v)", name, id, err)
			}
		}
		return nil
	}
}
