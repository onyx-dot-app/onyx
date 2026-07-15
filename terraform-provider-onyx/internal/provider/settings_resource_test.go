package provider

import (
	"context"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
)

func TestAccSettingsResource(t *testing.T) {
	// The settings singleton is global deployment state and destroy is
	// deliberately a no-op, so snapshot the fields this test touches and
	// restore them afterwards.
	var restore func()

	resource.Test(t, resource.TestCase{
		PreCheck: func() {
			testAccPreCheck(t)
			restore = snapshotSettingsFields(t)
			t.Cleanup(restore)
		},
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_settings" "test" {
  company_name = "tf-acc-corp"
  auto_scroll  = true
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_settings.test", "id", "settings"),
					resource.TestCheckResourceAttr("onyx_settings.test", "company_name", "tf-acc-corp"),
					resource.TestCheckResourceAttr("onyx_settings.test", "auto_scroll", "true"),
					// License-derived fields must be populated read-only.
					resource.TestCheckResourceAttrSet("onyx_settings.test", "tier"),
					resource.TestCheckResourceAttrSet("onyx_settings.test", "application_status"),
					// Unmanaged fields stay null: no value, no drift.
					resource.TestCheckNoResourceAttr("onyx_settings.test", "company_description"),
				),
			},
			{
				Config: `
resource "onyx_settings" "test" {
  company_name = "tf-acc-corp-renamed"
  auto_scroll  = false
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_settings.test", "company_name", "tf-acc-corp-renamed"),
					resource.TestCheckResourceAttr("onyx_settings.test", "auto_scroll", "false"),
				),
			},
			{
				ResourceName:      "onyx_settings.test",
				ImportState:       true,
				ImportStateId:     "settings",
				ImportStateVerify: true,
				// Freshly imported state has every writable field null
				// (unmanaged) — only the fields this config manages diverge.
				ImportStateVerifyIgnore: []string{"company_name", "auto_scroll"},
			},
		},
	})
}

// snapshotSettingsFields records the current values of the settings fields
// this test writes and returns a restore func run at cleanup.
func snapshotSettingsFields(t *testing.T) func() {
	t.Helper()
	c := testAccClient(t)
	before, err := c.GetSettings(context.Background())
	if err != nil {
		t.Fatalf("failed to snapshot settings: %v", err)
	}
	companyName := before.CompanyName
	autoScroll := before.AutoScroll

	return func() {
		current, err := c.GetSettings(context.Background())
		if err != nil {
			t.Logf("settings restore skipped: %v", err)
			return
		}
		current.CompanyName = companyName
		current.AutoScroll = autoScroll
		if err := c.PutSettings(context.Background(), *current); err != nil {
			t.Logf("settings restore failed: %v", err)
		}
	}
}
