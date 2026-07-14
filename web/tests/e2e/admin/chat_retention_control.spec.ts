import { test, expect } from "@tests/e2e/fixtures/eeFeatures";
import { loginAs } from "@tests/e2e/utils/auth";
import { ChatPreferencesPage } from "@tests/e2e/pages/ChatPreferencesPage";

test.describe("Chat retention control @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test.afterEach(async ({ page, eeEnabled }) => {
    if (!eeEnabled) return;
    await new ChatPreferencesPage(page)
      .resetRetentionToForever()
      .catch(() => {});
  });

  test("dropdown lists the configured retention presets", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    const chatPrefs = new ChatPreferencesPage(page);
    await chatPrefs.gotoAdvancedOptions();

    await chatPrefs.openRetentionDropdown();
    for (const label of [
      "Forever",
      "7 days",
      "30 days",
      "60 days",
      "90 days",
      "1 year",
      "Custom Retention",
    ]) {
      await expect(chatPrefs.retentionOption(label)).toBeVisible();
    }

    await page.keyboard.press("Escape");
  });

  test("Custom Retention converts the dropdown into a days input that persists", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    const chatPrefs = new ChatPreferencesPage(page);
    await chatPrefs.resetRetentionToForever();
    await chatPrefs.gotoAdvancedOptions();

    await chatPrefs.setCustomRetention("45");

    // In-place conversion: the dropdown is gone, replaced by the input.
    await expect(chatPrefs.retentionCustomInput).toBeVisible();
    await expect(chatPrefs.retentionTrigger).toHaveCount(0);

    // 45 is not a preset, so it round-trips back into the custom input.
    await chatPrefs.reloadAdvancedOptions();
    await expect(chatPrefs.retentionCustomInput).toHaveValue("45");
  });

  test("Restore Default returns retention to Forever", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    const chatPrefs = new ChatPreferencesPage(page);
    await chatPrefs.resetRetentionToForever();
    await chatPrefs.gotoAdvancedOptions();

    await chatPrefs.setCustomRetention("45");
    await chatPrefs.restoreRetentionDefault();

    await expect(chatPrefs.retentionTrigger).toContainText("Forever");
  });

  test("reducing retention prompts confirmation; cancel keeps the current value", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    const chatPrefs = new ChatPreferencesPage(page);
    await chatPrefs.resetRetentionToForever();
    await chatPrefs.gotoAdvancedOptions();

    await chatPrefs.selectRetentionPreset("30 days");
    await expect(chatPrefs.reduceRetentionModal).toBeVisible();

    await chatPrefs.cancelRetentionReduction();

    // The value was not changed.
    await expect(chatPrefs.retentionTrigger).toContainText("Forever");
  });
});
