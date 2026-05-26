import { test, expect } from "@playwright/test";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";

test.describe.configure({ mode: "parallel" });

for (const theme of THEMES) {
  test.describe(`Maintenance in Progress page (${theme} mode)`, () => {
    test.beforeEach(async ({ page }) => {
      await setThemeBeforeNavigation(page, theme);

      // Force the SettingsProvider into its fatal-error branch by failing the
      // core settings request with a non-auth status. When the web build has
      // NEXT_PUBLIC_CLOUD_ENABLED=true, this renders the CloudError
      // ("Maintenance in Progress") page.
      await page.route("**/api/settings", async (route) => {
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Simulated outage" }),
        });
      });
      await page.route("**/api/enterprise-settings", async (route) => {
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Simulated outage" }),
        });
      });
    });

    test("renders the Maintenance in Progress page", async ({ page }) => {
      await page.goto("/app");

      await expect(
        page.getByText("Maintenance in Progress", { exact: true })
      ).toBeVisible({ timeout: 15000 });
      await expect(
        page.getByText(
          "Onyx is currently in a maintenance window. Please check back in a couple of minutes."
        )
      ).toBeVisible();

      await expectScreenshot(page, {
        name: `maintenance-page-${theme}`,
      });
    });
  });
}
