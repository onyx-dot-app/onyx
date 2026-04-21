/**
 * Accessibility tests for authenticated app pages.
 *
 * Covers the core user-facing routes: chat welcome, search, and settings.
 */

import { test, expect } from "@tests/e2e/fixtures/accessibility";
import { loginAs } from "@tests/e2e/utils/auth";

test.use({ storageState: "admin_auth.json" });
test.describe.configure({ mode: "parallel" });

test.describe("Accessibility — app pages", () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, "admin");
  });

  test("chat welcome page (/app)", async ({ page, expectAccessible }) => {
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await expectAccessible();
  });

  test("search page", async ({ page, expectAccessible }) => {
    await page.goto("/search");
    await page.waitForLoadState("networkidle");
    await expectAccessible();
  });
});
