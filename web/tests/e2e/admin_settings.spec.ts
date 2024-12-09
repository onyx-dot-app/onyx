import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Settings - Workspace Settings",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/settings");
    await expect(page.locator("h1.text-3xl")).toHaveText("Workspace Settings");
    await expect(page.locator("p.text-sm").nth(0)).toHaveText(
      /^Manage general Danswer settings applicable to all users in the workspace./
    );
    await expect(
      page.getByRole("button", { name: "Set Retention Limit" })
    ).toHaveCount(1);
  }
);
