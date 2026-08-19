import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";

test.use({ storageState: "admin_auth.json" });
test.describe.configure({ mode: "parallel" });

/**
 * Discover all navigable admin pages by collecting links from the sidebar.
 * The sidebar is rendered on every `/admin/*` page, so we visit one admin
 * route and scrape the `<a>` elements that are present for the current
 * user / feature-flag configuration.
 */
async function discoverAdminPages(page: Page): Promise<string[]> {
  await page.goto("/admin/configuration/language-models");
  await page.waitForLoadState("networkidle");

  return page.evaluate(() => {
    const sidebar = document.querySelector(".opal-sidebar-root__column");
    if (!sidebar) return [];

    const hrefs = new Set<string>();
    sidebar
      .querySelectorAll<HTMLAnchorElement>('a[href^="/admin/"]')
      .forEach((a) => hrefs.add(a.getAttribute("href")!));
    return Array.from(hrefs);
  });
}

/**
 * Admin routes excluded from the parallel visual-regression sweep because other
 * specs mutate their rendered content while this test is running.
 *
 * `/admin/indexing/status` renders the list of existing connectors. Several
 * specs create file connectors mid-run via `apiClient.createFileConnector(...)`
 * (agents, chat, permission-sync, inline file management), and since this
 * `describe` block runs in parallel, a connector row appearing or disappearing
 * during the screenshot yields non-deterministic baseline diffs. Excluding the
 * page here keeps the sweep stable; a shared visual baseline isn't a good fit
 * for a list whose contents depend on concurrent test state.
 */
const VISUAL_REGRESSION_EXCLUDED_PATHS = new Set<string>([
  "/admin/indexing/status",
]);

for (const theme of THEMES) {
  test(`Admin pages – ${theme} mode`, async ({ page }) => {
    await setThemeBeforeNavigation(page, theme);

    const adminHrefs = await discoverAdminPages(page);
    expect(
      adminHrefs.length,
      "Expected to discover at least one admin page from the sidebar"
    ).toBeGreaterThan(0);

    for (const href of adminHrefs) {
      // Skip pages whose content is mutated by other specs running in parallel.
      if (VISUAL_REGRESSION_EXCLUDED_PATHS.has(href)) continue;

      const slug = href.replace(/^\/admin\//, "").replace(/\//g, "--");

      await test.step(
        slug,
        async () => {
          await page.goto(href);

          try {
            await expect(
              page.locator('[aria-label="admin-page-title"]')
            ).toBeVisible({ timeout: 10000 });
          } catch (error) {
            console.error(`Failed to find admin-page-title for "${href}"`);
            throw error;
          }

          await page.waitForLoadState("networkidle");

          await expectScreenshot(page, {
            name: `admin-${theme}-${slug}`,
            mask: [
              '[data-testid="admin-date-range-selector-button"]',
              '[data-column-id="updated_at"]',
            ],
          });
        },
        { box: true }
      );
    }
  });
}
