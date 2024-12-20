import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - User Management - Groups",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/users");
    await expect(page.locator("h1.text-3xl")).toHaveText("Manage Users");
  }
);
