import { test, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

test.describe("EE Feature Redirect", () => {
  test("redirects to /chat with toast when EE features are not licensed", async ({
    page,
  }) => {
    await loginAs(page, "admin");

    // Navigate to an EE-only route
    await page.goto("/admin/theme");
    await page.waitForLoadState("networkidle");

    // If the page still shows the theme form, EE is licensed — skip
    const appNameInput = page.locator('[data-label="application-name-input"]');
    if (await appNameInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      test.skip(true, "Enterprise license is active — redirect does not apply");
    }

    // Should have been redirected to /chat
    await expect(page).toHaveURL(/\/chat/, { timeout: 10000 });

    // Toast should be visible with the license message
    const toastContainer = page.getByTestId("toast-container");
    await expect(toastContainer).toBeVisible({ timeout: 5000 });
    await expect(
      toastContainer.getByText(/only accessible with a paid license/i)
    ).toBeVisible();
  });
});
