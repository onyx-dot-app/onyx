/**
 * Accessibility scan for every settings tab.
 *
 * Navigates to /app/settings, discovers tabs from the left nav, then scans
 * each one.
 */

import { test, expect } from "@tests/e2e/fixtures/accessibility";

test.use({ storageState: "admin_auth.json" });

test("Accessibility — all settings pages", async ({
  page,
  expectAccessible,
}) => {
  await page.goto("/app/settings/general");

  const nav = page.getByTestId("settings-left-tab-navigation");
  await nav.waitFor({ state: "visible", timeout: 10_000 });

  const tabs = nav.locator("a");
  await expect(tabs.first()).toBeVisible({ timeout: 10_000 });
  const count = await tabs.count();

  for (let i = 0; i < count; i++) {
    const tab = tabs.nth(i);
    const href = await tab.getAttribute("href");
    const slug = href ? href.replace("/app/settings/", "") : `tab-${i}`;

    await test.step(`settings/${slug}`, async () => {
      await tab.click();
      await page.waitForLoadState("networkidle");
      await expectAccessible();
    });
  }
});
