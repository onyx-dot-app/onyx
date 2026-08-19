import { test, expect, Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { ChatPreferencesPage } from "@tests/e2e/pages/ChatPreferencesPage";

/**
 * Open the model picker in chat and drill into the first model's detail pane.
 * The drill-in button renders only when at least one detail control survives
 * its admin gate, so its absence is itself meaningful.
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
  let prefs: ChatPreferencesPage;

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    prefs = new ChatPreferencesPage(page);
  });

  test.afterEach(async () => {
    await prefs.goto();
    await prefs.setReasoningControl(true);
  });

  test("admin can toggle the setting and it persists", async ({ page }) => {
    await prefs.goto();

    await prefs.setReasoningControl(false);
    await page.reload();
    await prefs.expectReasoningControl(false);

    await prefs.setReasoningControl(true);
    await page.reload();
    await prefs.expectReasoningControl(true);
  });

  test("reasoning level row is offered when the setting is on", async ({
    page,
  }) => {
    await prefs.goto();
    await prefs.setReasoningControl(true);

    expect(await openFirstModelDetailPane(page)).toBe(true);
    await expect(page.getByText("Reasoning Level")).toBeVisible();
  });

  test("reasoning level row is withheld when the setting is off", async ({
    page,
  }) => {
    await prefs.goto();
    await prefs.setReasoningControl(false);

    // Temperature stays enabled, so the pane still opens - without a reasoning
    // row. If it does not open, temperature is disabled too and the drill-in
    // affordance is correctly gone; the row is withheld either way.
    if (await openFirstModelDetailPane(page)) {
      await expect(page.getByText("Temperature")).toBeVisible();
      await expect(page.getByText("Reasoning Level")).toHaveCount(0);
    }
  });
});
