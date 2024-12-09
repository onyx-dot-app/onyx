import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Performance - Custom Analytics",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/performance/custom-analytics");
    await expect(page.locator("h1.text-3xl")).toHaveText("Custom Analytics");
    await expect(page.locator("div.font-medium").nth(0)).toHaveText(
      "Custom Analytics is not enabled."
    );
  }
);
