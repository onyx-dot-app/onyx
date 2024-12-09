import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Document Management - Feedback",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/documents/feedback");
    await expect(page.locator("h1.text-3xl")).toHaveText("Document Feedback");
    await expect(page.locator("h1.text-lg").nth(0)).toHaveText(
      "Most Liked Documents"
    );
    await expect(page.locator("h1.text-lg").nth(1)).toHaveText(
      "Most Disliked Documents"
    );
  }
);
