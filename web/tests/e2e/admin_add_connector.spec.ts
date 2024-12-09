import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Connectors - Add Connector",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/add-connector");
    await expect(page.locator("h1.text-3xl")).toHaveText("Add Connector");
    await expect(page.locator("h1.text-lg").nth(0)).toHaveText(/^Storage/);
  }
);
