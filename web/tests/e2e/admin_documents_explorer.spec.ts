import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Document Management - Feedback",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/documents/explorer");
    await expect(page.locator("h1.text-3xl")).toHaveText("Document Explorer");
    await expect(page.locator("div.flex.text-emphasis.mt-3")).toHaveText(
      "Search for a document above to modify its boost or hide it from searches."
    );
  }
);
