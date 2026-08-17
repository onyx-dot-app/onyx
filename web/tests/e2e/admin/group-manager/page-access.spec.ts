/**
 * Which admin pages a scoped group manager reaches, and that each one renders.
 *
 * The sidebar is driven by `admin_capabilities` (effective permissions ∪ the scoped
 * bundle) while every route enforces its own gate, so the two can disagree in both
 * directions: a page offered but 403ing, or a page reachable but never linked. The
 * discovered set is asserted exactly — an extra entry is over-exposure, a missing one
 * is a manager locked out of their own work.
 */

import { worldTest as test, expect, actAsManager } from "./fixtures";

/**
 * Heading each page renders once its own content has loaded — the app has no <main>
 * landmark, and a heading proves the page body arrived rather than just the shell.
 */
const PAGE_HEADINGS: Record<string, string> = {
  "/admin/agents": "Agents",
  "/admin/actions/mcp": "MCP Actions",
  "/admin/actions/open-api": "OpenAPI Actions",
  "/admin/indexing/status": "Existing Connectors",
  "/admin/add-connector": "Add Connector",
  "/admin/documents/sets": "Document Sets",
};

/** Unlocked by the scoped bundle alone, with no feature flag or tier behind them. */
const ALWAYS_PAGES = [
  "/admin/actions/mcp",
  "/admin/actions/open-api",
  "/admin/agents",
];

/** Also require `vectorDbEnabled`. */
const VECTOR_DB_PAGES = [
  "/admin/add-connector",
  "/admin/documents/sets",
  "/admin/indexing/status",
];

/** Also requires Tier.BUSINESS, which the run's license decides. */
const TIER_GATED_PAGES = ["/admin/groups"];

/** Nothing outside this may ever appear — anything else is over-exposure. */
const ALLOWED_PAGES = [
  ...ALWAYS_PAGES,
  ...VECTOR_DB_PAGES,
  ...TIER_GATED_PAGES,
];

/** Admin-only pages that must not be linked, and must refuse a direct visit. */
const FORBIDDEN_PAGES = [
  "/admin/configuration/language-models",
  "/admin/users",
  "/admin/configuration/web-search",
];

// seeding a whole scoped world plus several re-logins puts these well past the
// default budget; the work is real, not a hang
test.describe.configure({ timeout: 240_000 });

test.describe("scoped manager admin surface", () => {
  test("sidebar exposes exactly the scoped-manager pages", async ({
    page,
    world,
  }) => {
    const managerClient = await actAsManager(page, world.manager);
    await page.goto("/admin/indexing/status");
    await page.waitForLoadState("networkidle");

    const hrefs = await page.evaluate(() => {
      const sidebar = document.querySelector(".opal-sidebar-root__column");
      if (!sidebar) return [];
      const found = new Set<string>();
      sidebar
        .querySelectorAll<HTMLAnchorElement>('a[href^="/admin/"]')
        .forEach((a) => found.add(a.getAttribute("href")!));
      return Array.from(found);
    });

    // over-exposure is the security half: nothing outside the bundle may appear
    expect(hrefs.sort()).toEqual(
      hrefs.filter((h) => ALLOWED_PAGES.includes(h)).sort()
    );
    // under-exposure: the unconditional pages must always be linked
    for (const path of ALWAYS_PAGES) {
      expect(hrefs, `${path} missing from the sidebar`).toContain(path);
    }
    // the rest only when their feature flag is on
    if (await managerClient.isVectorDbEnabled()) {
      for (const path of VECTOR_DB_PAGES) {
        expect(hrefs, `${path} missing with vector db enabled`).toContain(path);
      }
    }
  });

  test("every offered page renders for the manager", async ({
    page,
    world,
  }) => {
    const managerClient = await actAsManager(page, world.manager);
    const reachable = (await managerClient.isVectorDbEnabled())
      ? [...ALWAYS_PAGES, ...VECTOR_DB_PAGES]
      : ALWAYS_PAGES;

    for (const path of reachable) {
      await page.goto(path);
      // still on the page (not bounced to /chat or an access-denied route) and past
      // the loading state — a denied sub-fetch shows up as a permanent spinner
      await expect(page).toHaveURL(new RegExp(`${path}(\\?.*)?$`));
      await expect(
        page.getByText(PAGE_HEADINGS[path]!, { exact: true }).first()
      ).toBeVisible({ timeout: 30000 });
      // a denied sub-fetch leaves the page on its loader rather than erroring
      await expect(page.getByText("Loading …")).toHaveCount(0);
      await expect(
        page.getByText(/access denied|not authorized|403/i)
      ).toHaveCount(0);
    }
  });

  test("admin-only pages stay out of reach", async ({ page, world }) => {
    await actAsManager(page, world.manager);

    for (const path of FORBIDDEN_PAGES) {
      await page.goto(path);
      await expect(page).not.toHaveURL(new RegExp(`${path}$`));
    }
  });
});
