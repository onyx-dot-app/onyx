import { Page } from "@playwright/test";
import { test, expect } from "@tests/e2e/fixtures/eeFeatures";
import { loginAs } from "@tests/e2e/utils/auth";

const CHAT_PREFS_URL = "/admin/configuration/chat-preferences";

function retentionField(page: Page) {
  return page.locator("label").filter({ hasText: "Keep Chat History" });
}

function retentionTrigger(page: Page) {
  return retentionField(page).locator('[role="combobox"]');
}

function customInput(page: Page) {
  return retentionField(page).getByPlaceholder("In days");
}

// First icon button inside the custom input is "Restore Default" (the second
// is "More"). Tooltips don't set an accessible name, so target positionally.
function restoreDefaultButton(page: Page) {
  return retentionField(page)
    .locator(".opal-input")
    .getByRole("button")
    .first();
}

async function expandAdvancedOptions(page: Page): Promise<void> {
  await expect(page.locator('[aria-label="admin-page-title"]')).toBeVisible({
    timeout: 10000,
  });

  const header = page.getByText("Advanced Options", { exact: true });
  await expect(header).toBeVisible({ timeout: 10000 });

  const label = retentionField(page).first();
  if (await label.isVisible().catch(() => false)) return;

  await header.scrollIntoViewIfNeeded();
  await header.click();
  await expect(label).toBeVisible({ timeout: 5000 });
}

async function gotoChatPreferences(page: Page): Promise<void> {
  await page.goto(CHAT_PREFS_URL);
  await page.waitForLoadState("networkidle");
  await expandAdvancedOptions(page);
}

// Confirm a reduction (Forever -> finite value) and wait for the save toast.
async function confirmReduction(page: Page): Promise<void> {
  await expect(page.getByText("Reduce chat retention?")).toBeVisible({
    timeout: 5000,
  });
  await page.getByRole("button", { name: "Reduce retention" }).click();
  await expect(page.getByText("Settings updated")).toBeVisible({
    timeout: 5000,
  });
}

// Enter a custom retention of `days` starting from a Forever/larger value.
async function setCustomRetention(page: Page, days: string): Promise<void> {
  await retentionTrigger(page).click();
  await page
    .getByRole("option", { name: "Custom Retention", exact: true })
    .click();
  await expect(customInput(page)).toBeVisible();
  await customInput(page).fill(days);
  await customInput(page).blur();
  await confirmReduction(page);
}

async function resetToForever(page: Page): Promise<void> {
  await gotoChatPreferences(page);

  // Custom-input mode: Restore Default returns to Forever (an increase, so no
  // confirmation modal).
  if (
    await customInput(page)
      .isVisible()
      .catch(() => false)
  ) {
    await restoreDefaultButton(page).click();
    await expect(page.getByText("Settings updated"))
      .toBeVisible({ timeout: 5000 })
      .catch(() => {});
    return;
  }

  const trigger = retentionTrigger(page);
  if (((await trigger.textContent()) ?? "").includes("Forever")) return;
  await trigger.click();
  await page.getByRole("option", { name: "Forever", exact: true }).click();
  await expect(page.getByText("Settings updated")).toBeVisible({
    timeout: 5000,
  });
}

test.describe("Chat retention control @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test.afterEach(async ({ page, eeEnabled }) => {
    if (!eeEnabled) return;
    await resetToForever(page).catch(() => {});
  });

  test("dropdown lists the configured retention presets", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    await gotoChatPreferences(page);

    await retentionTrigger(page).click();

    for (const label of [
      "Forever",
      "1 year",
      "30 days",
      "60 days",
      "90 days",
      "Custom Retention",
    ]) {
      await expect(
        page.getByRole("option", { name: label, exact: true })
      ).toBeVisible();
    }
    // The legacy "7 days" preset was intentionally removed.
    await expect(
      page.getByRole("option", { name: "7 days", exact: true })
    ).toHaveCount(0);

    await page.keyboard.press("Escape");
  });

  test("Custom Retention converts the dropdown into a days input that persists", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    await resetToForever(page);
    await gotoChatPreferences(page);

    await setCustomRetention(page, "45");

    // In-place conversion: the dropdown is gone, replaced by the input.
    await expect(customInput(page)).toBeVisible();
    await expect(retentionTrigger(page)).toHaveCount(0);

    // 45 is not a preset, so it round-trips back into the custom input.
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expandAdvancedOptions(page);
    await expect(customInput(page)).toHaveValue("45");
  });

  test("Restore Default returns retention to Forever", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    await resetToForever(page);
    await gotoChatPreferences(page);

    await setCustomRetention(page, "45");

    await restoreDefaultButton(page).click();
    await expect(page.getByText("Settings updated")).toBeVisible({
      timeout: 5000,
    });

    await expect(retentionTrigger(page)).toContainText("Forever");
  });

  test("reducing retention prompts confirmation; cancel keeps the current value", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Chat retention requires an Enterprise license");
    await resetToForever(page);
    await gotoChatPreferences(page);

    await retentionTrigger(page).click();
    await page.getByRole("option", { name: "30 days", exact: true }).click();

    await expect(page.getByText("Reduce chat retention?")).toBeVisible({
      timeout: 5000,
    });

    // Cancel by dismissing the modal (no inputs inside, so Escape closes it).
    await page.keyboard.press("Escape");
    await expect(page.getByText("Reduce chat retention?")).toHaveCount(0);

    // The value was not changed.
    await expect(retentionTrigger(page)).toContainText("Forever");
  });
});
