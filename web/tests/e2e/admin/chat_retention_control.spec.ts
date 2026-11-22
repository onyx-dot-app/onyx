import { test, expect } from "@tests/e2e/fixtures/eeFeatures";
import { loginAs } from "@tests/e2e/utils/auth";
import { AdminSecurityPage } from "@tests/e2e/pages/AdminSecurityPage";

test.describe("Chat retention control @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test.afterEach(async ({ page, eeEnabled }) => {
    if (!eeEnabled) return;
    await new AdminSecurityPage(page).resetRetentionToForever().catch(() => {});
  });

  test("dropdown lists the configured retention presets", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    const security = new AdminSecurityPage(page);
    await security.goto();

    await security.openRetentionDropdown();
    for (const label of [
      "Forever",
      "7 days",
      "30 days",
      "60 days",
      "90 days",
      "1 year",
      "Custom Retention",
    ]) {
      await expect(security.retentionOption(label)).toBeVisible();
    }

    await page.keyboard.press("Escape");
  });

  test("Custom Retention converts the dropdown into a days input that persists", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    const security = new AdminSecurityPage(page);
    await security.resetRetentionToForever();
    await security.goto();

    await security.setCustomRetention("45");

    // In-place conversion: the dropdown is gone, replaced by the input.
    await expect(security.retentionCustomInput).toBeVisible();
    await expect(security.retentionTrigger).toHaveCount(0);

    // 45 is not a preset, so it round-trips back into the custom input.
    await security.reload();
    await expect(security.retentionCustomInput).toHaveValue("45");
  });

  test("Restore Default returns retention to Forever", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    const security = new AdminSecurityPage(page);
    await security.resetRetentionToForever();
    await security.goto();

    await security.setCustomRetention("45");
    await security.restoreRetentionDefault();

    await expect(security.retentionTrigger).toHaveValue("Forever");
  });

  test("reducing retention prompts confirmation; cancel keeps the current value", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    const security = new AdminSecurityPage(page);
    await security.resetRetentionToForever();
    await security.goto();

    await security.selectRetentionPreset("30 days");
    await expect(security.reduceRetentionModal).toBeVisible();

    await security.cancelRetentionReduction();

    // The value was not changed.
    await expect(security.retentionTrigger).toHaveValue("Forever");
  });
});
