import { test, expect } from "@tests/e2e/fixtures/eeFeatures";

test.describe("EE Feature Redirect", () => {
  test("redirects to /app when EE features are not licensed", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(eeEnabled, "Redirect only happens without Enterprise license");

    await page.goto("/admin/theme");

    await expect(page).toHaveURL(/\/app/, { timeout: 10_000 });
  });
});
