import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Connectors - Existing Connectors",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/indexing/status");
    await expect(page.locator("h1.text-3xl")).toHaveText("Existing Connectors");
    await expect(page.locator("p.text-sm")).toHaveText(
      /^It looks like you don't have any connectors setup yet./
    );
  }
);
