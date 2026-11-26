import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { test, expect } from "@tests/e2e/fixtures/eeFeatures";
import { loginAs } from "@tests/e2e/utils/auth";
import {
  AdminSecurityPage,
  QUERY_HISTORY_LABELS,
} from "@tests/e2e/pages/AdminSecurityPage";

test.describe("Query History Toggle @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test.afterEach(async ({ page }) => {
    await new AdminSecurityPage(page).setQueryHistoryType(
      "Show with User Info"
    );
  });

  test("dropdown shows current value and persists after reload", async ({
    page,
  }) => {
    const security = new AdminSecurityPage(page);
    await security.goto();

    expect(QUERY_HISTORY_LABELS).toContain(
      await security.getQueryHistoryValue()
    );

    await security.setQueryHistoryType("Anonymized");

    await security.reload();
    expect(await security.getQueryHistoryValue()).toBe("Anonymized");
  });

  test("setting to Hidden hides query history sidebar link", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Query History page requires enterprise license");
    const security = new AdminSecurityPage(page);

    await security.setQueryHistoryType("Show with User Info");

    await page.goto(ADMIN_ROUTES.USAGE.path);
    await page.waitForLoadState("networkidle");

    const sidebar = page.locator(".opal-sidebar-root__column");
    const queryHistoryLink = sidebar.locator(
      `a[href="${ADMIN_ROUTES.QUERY_HISTORY.path}"]`
    );
    await expect(queryHistoryLink).toBeVisible({ timeout: 5000 });

    await security.setQueryHistoryType("Hidden");

    await page.goto(ADMIN_ROUTES.USAGE.path);
    await page.waitForLoadState("networkidle");

    const sidebarAfter = page.locator(".opal-sidebar-root__column");
    const queryHistoryLinkAfter = sidebarAfter.locator(
      `a[href="${ADMIN_ROUTES.QUERY_HISTORY.path}"]`
    );
    await expect(queryHistoryLinkAfter).not.toBeVisible({ timeout: 5000 });
  });

  test("can cycle through all three options", async ({ page }) => {
    const security = new AdminSecurityPage(page);
    for (const label of QUERY_HISTORY_LABELS) {
      await security.setQueryHistoryType(label);
      await security.reload();
      expect(await security.getQueryHistoryValue()).toBe(label);
    }
  });
});
