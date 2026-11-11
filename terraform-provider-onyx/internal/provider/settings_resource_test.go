package provider

import (
	"context"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
)

func TestAccSettingsResource(t *testing.T) {
	// Destroy is a deliberate no-op on the global singleton, so snapshot and
	// restore the fields this test touches.
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

  reasoning_override_enabled = false
  hide_provider_grouping     = true
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_settings.test", "reasoning_override_enabled", "false"),
					resource.TestCheckResourceAttr("onyx_settings.test", "hide_provider_grouping", "true"),
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
	// PATCH merges only sent fields; a nil pointer encodes as JSON null and
	// restores "unset".
	restore := map[string]any{
		"company_name":               before.CompanyName,
		"auto_scroll":                before.AutoScroll,
		"reasoning_override_enabled": before.ReasoningOverrideEnabled,
	}
	// Not nullable server-side, so restore it only when it was read.
	if before.HideProviderGrouping != nil {
		restore["hide_provider_grouping"] = *before.HideProviderGrouping
	}

	return func() {
		err := c.PatchSettings(context.Background(), restore)
		if err != nil {
			// A failed restore leaves the shared deployment modified.
			t.Errorf("settings restore failed: %v", err)
		}
	}
}
