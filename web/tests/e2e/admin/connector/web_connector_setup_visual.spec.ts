import { test, expect } from "@playwright/test";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { ConnectorSetupPage } from "@tests/e2e/admin/connector/ConnectorSetupPage";

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

    const setupPage = new ConnectorSetupPage(page, "web");
    await setupPage.goto();

    await expect(setupPage.textField("base_url")).toBeVisible();
    await page.waitForLoadState("networkidle");

    await setupPage.expectScreenshot(`admin-${theme}-connectors--web--step-1`);
  });
}
