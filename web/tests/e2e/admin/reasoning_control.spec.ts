import { test, expect, Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

const MAX_SETTING_SAVE_ATTEMPTS = 5;
const CHAT_PREFERENCES_PATH = "/admin/configuration/chat-preferences";

/**
 * Set the "Reasoning Control" switch and confirm it survives a reload.
 *
 * The switch sits above the "Advanced Options" collapsible, so unlike
 * `disable_default_agent.spec.ts` there is nothing to expand first. Saving is
 * a PATCH of the whole settings blob, so a concurrent writer can clobber it —
 * hence the retry.
 */
async function setReasoningControl(
  page: Page,
  enabled: boolean
): Promise<void> {
  let lastState = false;

  for (let attempt = 0; attempt < MAX_SETTING_SAVE_ATTEMPTS; attempt += 1) {
    await page.goto(CHAT_PREFERENCES_PATH);
    await page.waitForLoadState("networkidle");

    const switchEl = page.locator("#reasoning_override_enabled");
    await expect(switchEl).toBeVisible({ timeout: 10000 });

    lastState = (await switchEl.getAttribute("aria-checked")) === "true";
    if (lastState === enabled) return;

    await switchEl.click();
    await expect(page.getByText("Settings updated")).toBeVisible({
      timeout: 5000,
    });

    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(switchEl).toBeVisible({ timeout: 10000 });

    lastState = (await switchEl.getAttribute("aria-checked")) === "true";
    if (lastState === enabled) return;
  }

  throw new Error(
    `Failed to persist Reasoning Control after ${MAX_SETTING_SAVE_ATTEMPTS} attempts (expected ${enabled}, last=${lastState}).`
  );
}

/**
 * Open the model picker in chat and drill into the first model's detail pane.
 * The drill-in button only renders when at least one detail block is enabled,
 * so its absence is itself meaningful.
 */
async function openFirstModelDetailPane(page: Page): Promise<boolean> {
  await page.goto("/app");
  await page.waitForLoadState("networkidle");

  await page.getByTestId("model-selector").click();

  const settingsButton = page
    .getByRole("button", { name: /settings$/ })
    .first();
  if (!(await settingsButton.isVisible().catch(() => false))) return false;

  await settingsButton.click();
  return true;
}

test.describe("Reasoning Control setting @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test.afterEach(async ({ page }) => {
    await setReasoningControl(page, true);
  });

  test("admin can toggle the setting and it persists", async ({ page }) => {
    await setReasoningControl(page, false);
    await setReasoningControl(page, true);
    await setReasoningControl(page, false);
  });

  test("reasoning level row is offered when the setting is on", async ({
    page,
  }) => {
    await setReasoningControl(page, true);

    expect(await openFirstModelDetailPane(page)).toBe(true);
    await expect(page.getByText("Reasoning Level")).toBeVisible({
      timeout: 5000,
    });
  });

  test("reasoning level row is withheld when the setting is off", async ({
    page,
  }) => {
    await setReasoningControl(page, false);

    const paneOpened = await openFirstModelDetailPane(page);
    if (paneOpened) {
      // Temperature is still enabled, so the pane opens without a reasoning row.
      await expect(page.getByText("Temperature")).toBeVisible({
        timeout: 5000,
      });
      await expect(page.getByText("Reasoning Level")).toHaveCount(0);
    }
    // If the pane did not open at all, temperature is also disabled and the
    // drill-in affordance is correctly gone — the row is withheld either way.
  });
});
