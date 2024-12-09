import { test, expect } from "@chromatic-com/playwright";

test.describe("Admin Performance Query History", () => {
  // Ignores the diff for elements targeted by the specified list of selectors
  // exclude button since they change based on the date
  test.use({ ignoreSelectors: ["button"] });

  test(
    "Admin - Performance - Query History",
    {
      tag: "@admin",
    },
    async ({ page }, testInfo) => {
      // Test simple loading
      await page.goto("http://localhost:3000/admin/performance/query-history");
      await expect(page.locator("h1.text-3xl")).toHaveText("Query History");
      await expect(page.locator("p.text-sm").nth(0)).toHaveText(
        "Feedback Type"
      );
    }
  );
});
