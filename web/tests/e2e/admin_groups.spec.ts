import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - User Management - Groups",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/groups");
    await expect(page.locator("h1.text-3xl")).toHaveText("Manage User Groups");
    await expect(
      page.getByRole("button", { name: "Create New User Group" })
    ).toHaveCount(1);
  }
);
