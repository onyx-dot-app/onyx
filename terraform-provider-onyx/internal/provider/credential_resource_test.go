package provider

import (
	"context"
	"fmt"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

func TestAccCredentialResource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckCredentialDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_credential" "test" {
  source = "confluence"
  name   = "tf-acc-credential"
  credential_json = jsonencode({
    confluence_username     = "tf-acc@example.com"
    confluence_access_token = "tf-acc-fake-token"
  })
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_credential.test", "source", "confluence"),
					resource.TestCheckResourceAttr("onyx_credential.test", "name", "tf-acc-credential"),
					resource.TestCheckResourceAttr("onyx_credential.test", "admin_public", "true"),
					resource.TestCheckResourceAttr("onyx_credential.test", "curator_public", "false"),
					resource.TestCheckResourceAttrSet("onyx_credential.test", "id"),
				),
			},
			{
				ResourceName:      "onyx_credential.test",
				ImportState:       true,
				ImportStateVerify: true,
				// The API only ever returns the payload masked.
				ImportStateVerifyIgnore: []string{"credential_json"},
			},
			{
				// Rename and rotate the secret in one apply: the rename endpoint
				// merges, so it must run after the payload replacement.
				Config: `
resource "onyx_credential" "test" {
  source = "confluence"
  name   = "tf-acc-credential-renamed"
  credential_json = jsonencode({
    confluence_username     = "tf-acc@example.com"
    confluence_access_token = "tf-acc-fake-token-rotated"
  })
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_credential.test", "name", "tf-acc-credential-renamed"),
					testAccCheckCredentialTokenStored(t, "tf-acc-fake-token-rotated"),
				),
			},
		},
	})
}

// testAccCheckCredentialTokenStored asserts the rotated secret reached the
// server. The read-back is masked as first4...last4, so this compares the
// visible ends.
func testAccCheckCredentialTokenStored(t *testing.T, wantToken string) resource.TestCheckFunc {
	return func(s *terraform.State) error {
		rs, ok := s.RootModule().Resources["onyx_credential.test"]
		if !ok {
			return fmt.Errorf("onyx_credential.test not found in state")
		}
		id, err := parseIDString(rs.Primary.ID)
		if err != nil {
			return err
		}
		remote, err := testAccClient(t).GetCredential(context.Background(), id)
		if err != nil {
			return err
		}
		stored, _ := remote.CredentialJSON["confluence_access_token"].(string)
		want := fmt.Sprintf("%s...%s", wantToken[:4], wantToken[len(wantToken)-4:])
		if stored != want {
			return fmt.Errorf("stored token reads %q, want %q — the configured value did not land", stored, want)
		}
		return nil
	}
}

func testAccCheckCredentialDestroyed(t *testing.T) resource.TestCheckFunc {
	return func(s *terraform.State) error {
		c := testAccClient(t)
		for name, rs := range s.RootModule().Resources {
			if rs.Type != "onyx_credential" {
				continue
			}
			id, err := parseIDString(rs.Primary.ID)
			if err != nil {
				return err
			}
			if _, err := c.GetCredential(context.Background(), id); !client.IsNotFound(err) {
				return fmt.Errorf("%s: credential %s still exists after destroy (err: %v)", name, rs.Primary.ID, err)
			}
		}
		return nil
	}
}
