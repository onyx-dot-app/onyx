import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - User Management - API Keys",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/api-key");
    await expect(page.locator("h1.text-3xl")).toHaveText("API Keys");
    await expect(page.locator("p.text-sm")).toHaveText(
      /^API Keys allow you to access Danswer APIs programmatically/
    );
    await expect(
      page.getByRole("button", { name: "Create API Key" })
    ).toHaveCount(1);
  }
);
