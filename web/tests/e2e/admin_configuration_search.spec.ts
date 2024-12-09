import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Configuration - Search Settings",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/configuration/search");
    await expect(page.locator("h1.text-3xl")).toHaveText("Search Settings");
    await expect(page.locator("h1.text-lg").nth(0)).toHaveText(
      "Embedding Model"
    );
  }
);
