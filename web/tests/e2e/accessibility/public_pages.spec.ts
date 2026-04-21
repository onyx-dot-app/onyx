/**
 * Accessibility tests for unauthenticated (public) pages.
 *
 * These pages are the first thing users encounter and are most likely to be
 * evaluated by external auditors or automated compliance scanners.
 */

import { test, expect } from "@tests/e2e/fixtures/accessibility";

test.describe("Accessibility — public pages", () => {
  test.describe.configure({ mode: "parallel" });

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
  });

  test("login page", async ({ page, expectAccessible }) => {
    await page.goto("/auth/login");
    await page.waitForLoadState("networkidle");
    await expectAccessible();
  });

  test("signup page", async ({ page, expectAccessible }) => {
    await page.goto("/auth/signup");
    await page.waitForLoadState("networkidle");
    await expectAccessible();
  });
});
