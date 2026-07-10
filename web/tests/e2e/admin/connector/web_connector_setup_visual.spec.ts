import { test, expect } from "@playwright/test";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";

/**
 * Visual-regression coverage for the web connector setup wizard
 * (`/admin/connectors/web?step=1`).
 *
 * The admin-pages sweep (`admin_pages.spec.ts`) only visits pages linked from
 * the sidebar, so per-connector wizard pages are not covered by it. This page
 * renders the shared `RenderField`/`TextFormField` machinery used by every
 * connector's setup form, so a regression here (e.g. the Base URL input
 * rendering at the wrong height) affects all connectors.
 *
 * The page is a static form with no dependence on connectors created by other
 * specs, so it can safely run in the parallel `admin` project. Auth comes from
 * the project's `storageState`.
 */
for (const theme of THEMES) {
  test(`web connector setup wizard – ${theme} mode`, async ({ page }) => {
    await setThemeBeforeNavigation(page, theme);

    await page.goto("/admin/connectors/web?step=1");

    await expect(page.locator('[aria-label="admin-page-title"]')).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("base_url")).toBeVisible();
    await page.waitForLoadState("networkidle");

    await expectScreenshot(page, {
      name: `admin-${theme}-connectors--web--step-1`,
    });
  });
}
