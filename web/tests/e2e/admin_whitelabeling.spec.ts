import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Performance - Whitelabeling",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/whitelabeling");
    await expect(page.locator("h1.text-3xl")).toHaveText("Whitelabeling");
    await expect(page.locator("div.block").nth(0)).toHaveText(
      "Application Name"
    );
    await expect(page.locator("div.block").nth(1)).toHaveText("Custom Logo");
    await expect(page.getByRole("button", { name: "Update" })).toHaveCount(1);
  }
);
