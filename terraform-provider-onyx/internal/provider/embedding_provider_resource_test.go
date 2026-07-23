package provider

import (
	"context"
	"fmt"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

func TestAccEmbeddingProviderResource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckEmbeddingProviderDestroyed(t),
		Steps: []resource.TestStep{
			{
				// voyage is the least likely provider type to be configured
				// on a dev deployment already.
				Config: `
resource "onyx_embedding_provider" "test" {
  provider_type = "voyage"
  api_key       = "pa-tf-acc-fake-key"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_embedding_provider.test", "id", "voyage"),
					resource.TestCheckResourceAttr("onyx_embedding_provider.test", "provider_type", "voyage"),
					// The configured secret must be in state, not the masked
					// read-back value.
					resource.TestCheckResourceAttr("onyx_embedding_provider.test", "api_key", "pa-tf-acc-fake-key"),
				),
			},
			{
				ResourceName:      "onyx_embedding_provider.test",
				ImportState:       true,
				ImportStateId:     "voyage",
				ImportStateVerify: true,
				// The API only ever returns the key masked, so imported state
				// has it null.
				ImportStateVerifyIgnore: []string{"api_key"},
			},
			{
				// Rotate the key and set a URL; the update must send the new
				// raw values (a masked write-back would corrupt the stored key
				// — verified server-side below).
				Config: `
resource "onyx_embedding_provider" "test" {
  provider_type = "voyage"
  api_key       = "pa-tf-acc-fake-key-rotated"
  api_url       = "https://api.voyageai.example.com/v1"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_embedding_provider.test", "api_key", "pa-tf-acc-fake-key-rotated"),
					resource.TestCheckResourceAttr("onyx_embedding_provider.test", "api_url", "https://api.voyageai.example.com/v1"),
					testAccCheckEmbeddingKeyNotMasked(t, "voyage"),
				),
			},
		},
	})
}

// testAccCheckEmbeddingKeyNotMasked guards against the masked-value write-back
// hazard: the server-side masked key must reflect a real stored value, not a
// doubly-masked placeholder (mask characters written back as the key).
func testAccCheckEmbeddingKeyNotMasked(t *testing.T, providerType string) resource.TestCheckFunc {
	return func(_ *terraform.State) error {
		remote, err := testAccClient(t).GetEmbeddingProvider(context.Background(), providerType)
		if err != nil {
			return err
		}
		if remote.APIKey == nil || *remote.APIKey == "" {
			return fmt.Errorf("stored api_key is empty after update — the raw key was not persisted")
		}
		// The mask keeps a real key's prefix; a corrupted (masked-then-stored)
		// key would start with the mask filler instead of the raw prefix.
		masked := *remote.APIKey
		if len(masked) < 2 || masked[:2] != "pa" {
			return fmt.Errorf("stored api_key looks corrupted (masked value written back?): %q", masked)
		}
		return nil
	}
}

func testAccCheckEmbeddingProviderDestroyed(t *testing.T) resource.TestCheckFunc {
	return func(s *terraform.State) error {
		c := testAccClient(t)
		for name, rs := range s.RootModule().Resources {
			if rs.Type != "onyx_embedding_provider" {
				continue
			}
			if _, err := c.GetEmbeddingProvider(context.Background(), rs.Primary.ID); !client.IsNotFound(err) {
				return fmt.Errorf("%s: embedding provider %q still exists after destroy (err: %v)", name, rs.Primary.ID, err)
			}
		}
		return nil
	}
}
