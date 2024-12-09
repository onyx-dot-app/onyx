import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Document Management - Document Sets",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/documents/sets");
    await expect(page.locator("h1.text-3xl")).toHaveText("Document Sets");
    await expect(page.locator("p.text-sm")).toHaveText(
      /^Document Sets allow you to group logically connected documents into a single bundle./
    );
  }
);
