package provider

import (
	"context"
	"fmt"
	"regexp"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/acctest"
	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
)

// testAccRequireEE skips unless the deployment runs Enterprise Edition. The
// group routes live in the EE app and answer 404 without it.
//
// Call it after testAccPreCheck: it needs the bootstrapped key.
func testAccRequireEE(t *testing.T) {
	t.Helper()
	settings, err := testAccClient(t).GetSettings(context.Background())
	if err != nil {
		t.Fatalf("reading settings to detect Enterprise Edition failed: %v", err)
	}
	if !settings.EEFeaturesEnabled {
		t.Skip("user groups are an Enterprise Edition feature; this deployment runs Community Edition")
	}
}

func TestAccUserGroupResource(t *testing.T) {
	// Both helpers read the bootstrapped key, and step configurations are built
	// before resource.Test runs its own PreCheck, so the bootstrap has to happen
	// here.
	testAccPreCheck(t)
	testAccRequireEE(t)
	userID := testAccCurrentUserID(t)

	// Group names are unique across the deployment, so a run that dies before
	// its cleanup would block every later run on the name.
	name := acctest.RandomWithPrefix("tf-acc-group")

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckUserGroupDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_user_group" "test" {
  name = "` + name + `"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_user_group.test", "name", name),
					resource.TestCheckResourceAttr("onyx_user_group.test", "is_default", "false"),
					resource.TestCheckResourceAttr("onyx_user_group.test", "incognito_enabled", "false"),
					// Every collection defaults to empty rather than null, so an
					// unstated one does not report a change back to null.
					resource.TestCheckResourceAttr("onyx_user_group.test", "user_ids.#", "0"),
					resource.TestCheckResourceAttr("onyx_user_group.test", "manager_ids.#", "0"),
					resource.TestCheckResourceAttr("onyx_user_group.test", "permissions.#", "0"),
					resource.TestCheckResourceAttr("onyx_user_group.test", "cc_pair_ids.#", "0"),
					resource.TestCheckResourceAttrSet("onyx_user_group.test", "id"),
				),
			},
			{
				// This step sits immediately after the create on purpose. A new
				// group is left syncing, and rename and membership are both
				// refused while it is, so this is what proves the provider waits
				// rather than a later step having given the sync time by accident.
				Config: `
resource "onyx_user_group" "test" {
  name              = "` + name + `-renamed"
  user_ids          = ["` + userID + `"]
  manager_ids       = ["` + userID + `"]
  permissions       = ["manage:connectors", "read:query_history"]
  incognito_enabled = true
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_user_group.test", "name", name+"-renamed"),
					resource.TestCheckResourceAttr("onyx_user_group.test", "user_ids.#", "1"),
					resource.TestCheckResourceAttr("onyx_user_group.test", "manager_ids.#", "1"),
					resource.TestCheckTypeSetElemAttr("onyx_user_group.test", "user_ids.*", userID),
					resource.TestCheckTypeSetElemAttr("onyx_user_group.test", "manager_ids.*", userID),
					resource.TestCheckResourceAttr("onyx_user_group.test", "permissions.#", "2"),
					resource.TestCheckTypeSetElemAttr("onyx_user_group.test", "permissions.*", "manage:connectors"),
					resource.TestCheckResourceAttr("onyx_user_group.test", "incognito_enabled", "true"),
				),
			},
			{
				// Demote the manager but keep the membership, so the demotion is
				// exercised on its own rather than riding a roster removal.
				Config: `
resource "onyx_user_group" "test" {
  name              = "` + name + `-renamed"
  user_ids          = ["` + userID + `"]
  permissions       = ["manage:connectors"]
  incognito_enabled = false
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_user_group.test", "user_ids.#", "1"),
					resource.TestCheckResourceAttr("onyx_user_group.test", "manager_ids.#", "0"),
					resource.TestCheckResourceAttr("onyx_user_group.test", "permissions.#", "1"),
					resource.TestCheckResourceAttr("onyx_user_group.test", "incognito_enabled", "false"),
				),
			},
			{
				// Empty the roster and revoke every grant, proving an omitted
				// list clears rather than leaving the stored one alone.
				Config: `
resource "onyx_user_group" "test" {
  name = "` + name + `-renamed"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_user_group.test", "user_ids.#", "0"),
					resource.TestCheckResourceAttr("onyx_user_group.test", "permissions.#", "0"),
				),
			},
			{
				ResourceName:      "onyx_user_group.test",
				ImportState:       true,
				ImportStateVerify: true,
			},
		},
	})
}

// The membership endpoint replaces connector links along with members, and
// onyx_cc_pair owns those links. This is the end-to-end guard for that: the
// roster changes twice and the connector stays shared with the group.
func TestAccUserGroupKeepsConnectorLinksWhenTheRosterChanges(t *testing.T) {
	testAccPreCheck(t)
	testAccRequireEE(t)
	userID := testAccCurrentUserID(t)
	name := acctest.RandomWithPrefix("tf-acc-group-links")

	// mock_connector short-circuits the connector's real settings check, so the
	// pair needs no live source. See the cc_pair tests.
	dependencies := `
resource "onyx_connector" "links" {
  name                      = "` + name + `-connector"
  source                    = "mock_connector"
  input_type                = "poll"
  connector_specific_config = jsonencode({})
}

resource "onyx_credential" "links" {
  name            = "` + name + `-credential"
  source          = "mock_connector"
  credential_json = jsonencode({})
}

resource "onyx_cc_pair" "links" {
  name          = "` + name + `-pair"
  connector_id  = onyx_connector.links.id
  credential_id = onyx_credential.links.id
  access_type   = "private"
  groups        = [onyx_user_group.links.id]
}
`

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckUserGroupDestroyed(t),
		Steps: []resource.TestStep{
			{
				// cc_pair_ids is not asserted yet. Terraform creates the group
				// before the pair that references it, so the mirror is still
				// empty in this step's state; the next refresh fills it in.
				Config: dependencies + `
resource "onyx_user_group" "links" {
  name = "` + name + `"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_user_group.links", "user_ids.#", "0"),
					resource.TestCheckResourceAttrSet("onyx_cc_pair.links", "id"),
				),
			},
			{
				// Adding a member rewrites the group through the endpoint that
				// also owns connector links. Without the echo-back the pair is
				// silently unshared here.
				Config: dependencies + `
resource "onyx_user_group" "links" {
  name     = "` + name + `"
  user_ids = ["` + userID + `"]
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_user_group.links", "user_ids.#", "1"),
					resource.TestCheckResourceAttr("onyx_user_group.links", "cc_pair_ids.#", "1"),
					resource.TestCheckResourceAttrPair(
						"onyx_user_group.links", "cc_pair_ids.0", "onyx_cc_pair.links", "id"),
				),
			},
			{
				// And removing one again.
				Config: dependencies + `
resource "onyx_user_group" "links" {
  name = "` + name + `"
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_user_group.links", "user_ids.#", "0"),
					resource.TestCheckResourceAttr("onyx_user_group.links", "cc_pair_ids.#", "1"),
				),
			},
		},
	})
}

// Group names are unique, and a create landing on a live name is refused
// rather than quietly adopting the group.
func TestAccUserGroupRejectsADuplicateName(t *testing.T) {
	testAccPreCheck(t)
	testAccRequireEE(t)
	name := acctest.RandomWithPrefix("tf-acc-group-dup")

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckUserGroupDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_user_group" "first" {
  name = "` + name + `"
}
`,
			},
			{
				Config: `
resource "onyx_user_group" "first" {
  name = "` + name + `"
}

resource "onyx_user_group" "second" {
  name = "` + name + `"
}
`,
				ExpectError: regexp.MustCompile(`(?s)already exists`),
			},
		},
	})
}

// A manager is stored on the membership row, so Onyx cannot make one out of a
// non-member. The resource says so at plan time rather than failing the apply.
func TestAccUserGroupRejectsAManagerWhoIsNotAMember(t *testing.T) {
	testAccPreCheck(t)
	testAccRequireEE(t)
	name := acctest.RandomWithPrefix("tf-acc-group-manager")

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_user_group" "test" {
  name        = "` + name + `"
  user_ids    = ["11111111-1111-1111-1111-111111111111"]
  manager_ids = ["22222222-2222-2222-2222-222222222222"]
}
`,
				ExpectError: regexp.MustCompile(`(?s)not a member of the group`),
			},
		},
	})
}

// An id that is only known at apply time must not fail the plan.
//
// The manager-is-a-member check reads both lists at plan time, and reading an
// unknown id out of a set is an error rather than a skip, so an otherwise valid
// configuration whose ids come from another resource would be rejected before
// it ever ran. Plan-only: nothing is created.
func TestAccUserGroupAcceptsIDsThatAreUnknownAtPlanTime(t *testing.T) {
	testAccPreCheck(t)
	testAccRequireEE(t)
	name := acctest.RandomWithPrefix("tf-acc-group-unknown")

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_user_group" "anchor" {
  name = "` + name + `-anchor"
}

resource "onyx_user_group" "test" {
  name        = "` + name + `"
  user_ids    = [onyx_user_group.anchor.id]
  manager_ids = [onyx_user_group.anchor.id]
}
`,
				PlanOnly:           true,
				ExpectNonEmptyPlan: true,
			},
		},
	})
}

// A seeded default group holds members and nothing else. Asserted against the
// API rather than through Terraform: managing one would put the Admin group
// into state, and the destroy at the end of the test would try to delete it.
func TestAccUserGroupRefusesToRenameADefaultGroup(t *testing.T) {
	testAccPreCheck(t)
	testAccRequireEE(t)

	c := testAccClient(t)
	// Resolved through the helper rather than read off the bootstrap: setting
	// ONYX_TF_ACC_API_KEY short-circuits the bootstrap, which then never
	// records the id.
	adminGroupID := testAccAdminGroupID(t)

	_, err := c.RenameUserGroup(context.Background(), adminGroupID, "tf-acc-should-not-apply")
	if err == nil {
		t.Fatal("renaming a default system group must be refused")
	}
	if matched, _ := regexp.MatchString(`(?i)default system group`, err.Error()); !matched {
		t.Errorf("want a refusal naming the default group, got %v", err)
	}
}

// A follow-up call failing during create must report why.
//
// Managers, incognito and permissions are separate calls made after the group
// exists. Returning at the first failure left cc_pair_ids, document_set_ids,
// persona_ids and is_default unknown, and Terraform reported four provider bugs
// in place of the real reason. The group must also survive into state, or the
// one that now exists is leaked — the destroy check at the end proves it did.
func TestAccUserGroupReportsAFailedFollowUpCall(t *testing.T) {
	testAccPreCheck(t)
	testAccRequireEE(t)
	name := acctest.RandomWithPrefix("tf-acc-group-followup")

	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		CheckDestroy:             testAccCheckUserGroupDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_user_group" "followup" {
  name        = "` + name + `"
  permissions = ["not:a:real:permission"]
}
`,
				ExpectError: regexp.MustCompile(`(?s)Unable to set the user group permissions`),
			},
		},
	})
}

func testAccCheckUserGroupDestroyed(t *testing.T) resource.TestCheckFunc {
	return func(state *terraform.State) error {
		c := testAccClient(t)
		for name, rs := range state.RootModule().Resources {
			if rs.Type != "onyx_user_group" {
				continue
			}
			id, err := parseIDString(rs.Primary.ID)
			if err != nil {
				return err
			}
			_, found, err := c.LookupUserGroup(context.Background(), id)
			if err != nil {
				return fmt.Errorf("unexpected error reading %s after destroy: %w", name, err)
			}
			if found {
				return fmt.Errorf("%s (id %d) still exists after destroy", name, id)
			}
		}
		return nil
	}
}
