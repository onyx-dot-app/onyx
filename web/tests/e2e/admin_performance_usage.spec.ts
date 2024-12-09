import { test, expect } from "@chromatic-com/playwright";

test.describe("Admin Performance Usage", () => {
  // Ignores the diff for elements targeted by the specified list of selectors
  // exclude button and svg since they change based on the date
  test.use({ ignoreSelectors: ["button", "svg"] });

  test(
    "Admin - Performance - Usage Statistics",
    {
      tag: "@admin",
    },
    async ({ page }, testInfo) => {
      await page.goto("http://localhost:3000/admin/performance/usage");
      await expect(page.locator("h1.text-3xl")).toHaveText("Usage Statistics");
      await expect(page.locator("h1.text-lg").nth(0)).toHaveText("Usage");
      await expect(page.locator("h1.text-lg").nth(1)).toHaveText("Feedback");
    }
  );
});
