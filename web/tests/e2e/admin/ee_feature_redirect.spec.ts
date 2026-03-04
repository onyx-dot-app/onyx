import { test, expect } from "@tests/e2e/fixtures/eeFeatures";

test.describe("EE Feature Redirect", () => {
  test("redirects to /chat with toast when EE features are not licensed", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(eeEnabled, "Redirect only happens without Enterprise license");

    await page.goto("/admin/theme");

    await expect(page).toHaveURL(/\/chat/, { timeout: 10_000 });

    const toastContainer = page.getByTestId("toast-container");
    await expect(toastContainer).toBeVisible({ timeout: 5_000 });
    await expect(
      toastContainer.getByText(/only accessible with a paid license/i)
    ).toBeVisible();
  });
});
