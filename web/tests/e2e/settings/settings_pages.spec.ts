import { expect, test } from "@playwright/test";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";

test.use({ storageState: "admin_auth.json" });

for (const theme of THEMES) {
  test.describe(`Settings pages (${theme} mode)`, () => {
    test.beforeEach(async ({ page }) => {
      await setThemeBeforeNavigation(page, theme);
    });

    test("should screenshot each settings tab", async ({ page }) => {
      await page.goto("/app/settings");
      await page
        .getByTestId("settings-left-tab-navigation")
        .waitFor({ state: "visible" });

      const nav = page.getByTestId("settings-left-tab-navigation");
      const tabs = nav.locator("a");
      await expect(tabs.first()).toBeVisible({ timeout: 10_000 });
      const count = await tabs.count();

      for (let i = 0; i < count; i++) {
        const tab = tabs.nth(i);
        const href = await tab.getAttribute("href");
        const slug = href ? href.replace("/app/settings/", "") : `tab-${i}`;

        await tab.click();
        await page.waitForLoadState("networkidle");

        await expectScreenshot(page, {
          name: `settings-${theme}-${slug}`,
        });
      }
    });
  });
}
