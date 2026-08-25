package provider

import (
	"context"
	"fmt"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

// documentSetDependencies builds a pair for the set to hold. The names differ
// from the cc-pair test's so a leaked resource cannot collide.
const documentSetDependencies = `
resource "onyx_connector" "docset" {
  name                      = "tf-acc-docset-connector"
  source                    = "mock_connector"
  input_type                = "poll"
  connector_specific_config = jsonencode({})
}

resource "onyx_credential" "docset" {
  name            = "tf-acc-docset-credential"
  source          = "mock_connector"
  credential_json = jsonencode({})
}

resource "onyx_cc_pair" "docset" {
  name          = "tf-acc-docset-ccpair"
  connector_id  = onyx_connector.docset.id
  credential_id = onyx_credential.docset.id
}

# A second pair on the same connector, to prove cc_pair_ids is a full replace.
resource "onyx_credential" "docset_second" {
  name            = "tf-acc-docset-credential-second"
  source          = "mock_connector"
  credential_json = jsonencode({})
}

resource "onyx_cc_pair" "docset_second" {
  name          = "tf-acc-docset-ccpair-second"
  connector_id  = onyx_connector.docset.id
  credential_id = onyx_credential.docset_second.id
}
`

func TestAccDocumentSetResource(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckDocumentSetDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: documentSetDependencies + `
resource "onyx_document_set" "test" {
  name        = "tf-acc-docset"
  description = "Documents for the acceptance test"
  cc_pair_ids = [onyx_cc_pair.docset.id]
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_document_set.test", "name", "tf-acc-docset"),
					resource.TestCheckResourceAttr("onyx_document_set.test", "description", "Documents for the acceptance test"),
					resource.TestCheckResourceAttr("onyx_document_set.test", "is_public", "true"),
					resource.TestCheckResourceAttr("onyx_document_set.test", "cc_pair_ids.#", "1"),
					resource.TestCheckResourceAttrSet("onyx_document_set.test", "id"),
					// Optional collections left unset must stay null, or every
					// plan would report a change back to null.
					resource.TestCheckNoResourceAttr("onyx_document_set.test", "users.#"),
					resource.TestCheckNoResourceAttr("onyx_document_set.test", "groups.#"),
				),
			},
			{
				// This runs directly after the create on purpose. A new set is
				// left syncing, and Onyx rejects a change to a syncing set, so
				// the update has to wait for convergence before it writes.
				//
				// A full-replace update: rename, drop the description, make it
				// private, and swap the pair it holds. Onyx rejects a set with
				// no connectors at all, so the list is replaced, not emptied.
				Config: documentSetDependencies + `
resource "onyx_document_set" "test" {
  name        = "tf-acc-docset-renamed"
  cc_pair_ids = [onyx_cc_pair.docset_second.id]
  is_public   = false
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_document_set.test", "name", "tf-acc-docset-renamed"),
					resource.TestCheckResourceAttr("onyx_document_set.test", "description", ""),
					resource.TestCheckResourceAttr("onyx_document_set.test", "is_public", "false"),
					resource.TestCheckResourceAttr("onyx_document_set.test", "cc_pair_ids.#", "1"),
					resource.TestCheckTypeSetElemAttrPair(
						"onyx_document_set.test", "cc_pair_ids.*", "onyx_cc_pair.docset_second", "id"),
				),
			},
			{
				ResourceName:      "onyx_document_set.test",
				ImportState:       true,
				ImportStateVerify: true,
				// The background sync flips this on its own.
				ImportStateVerifyIgnore: []string{"is_up_to_date"},
			},
		},
	})
}

// testAccCheckDocumentSetDestroyed proves the destroy waited. Delete only
// marks the set, and the name is unique, so returning early would make the
// next apply fail on a name still in use.
func testAccCheckDocumentSetDestroyed(t *testing.T) resource.TestCheckFunc {
	return func(s *terraform.State) error {
		c := testAccClient(t)
		for name, rs := range s.RootModule().Resources {
			if rs.Type != "onyx_document_set" {
				continue
			}
			id, err := parseIDString(rs.Primary.ID)
			if err != nil {
				return err
			}
			set, err := c.GetDocumentSet(context.Background(), id)
			if client.IsNotFound(err) {
				continue
			}
			if err != nil {
				return fmt.Errorf("checking whether %s was destroyed: %w", name, err)
			}
			return fmt.Errorf("%s still exists as %q", name, set.Name)
		}
		return nil
	}
}
