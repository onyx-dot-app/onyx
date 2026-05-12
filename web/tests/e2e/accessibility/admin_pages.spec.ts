/**
 * Accessibility scan for every admin page discovered from the sidebar.
 *
 * Uses the same dynamic discovery approach as the visual regression admin
 * tests — scrapes sidebar links so the test automatically picks up new pages.
 */

import { test, expect } from "@tests/e2e/fixtures/accessibility";
import type { Page } from "@playwright/test";

test.use({ storageState: "admin_auth.json" });

async function discoverAdminPages(page: Page): Promise<string[]> {
  await page.goto("/admin/configuration/language-models");
  await page.waitForLoadState("networkidle");

  return page.evaluate(() => {
    const sidebar = document.querySelector('[class*="group/SidebarWrapper"]');
    if (!sidebar) return [];

    const hrefs = new Set<string>();
    sidebar
      .querySelectorAll<HTMLAnchorElement>('a[href^="/admin/"]')
      .forEach((a) => hrefs.add(a.getAttribute("href")!));
    return Array.from(hrefs);
  });
}

test("Accessibility — all admin pages", async ({ page, expectAccessible }) => {
  const adminHrefs = await discoverAdminPages(page);
  expect(
    adminHrefs.length,
    "Expected to discover at least one admin page"
  ).toBeGreaterThan(0);

  for (const href of adminHrefs) {
    const slug = href.replace(/^\/admin\//, "").replace(/\//g, "--");

    await test.step(`/admin/${slug}`, async () => {
      await page.goto(href);
      await page.waitForLoadState("networkidle");

      await expectAccessible({
        exclude: [
          // Dynamic date content that may not be accessible by default
          '[data-testid="admin-date-range-selector-button"]',
        ],
      });
    });
  }
});
