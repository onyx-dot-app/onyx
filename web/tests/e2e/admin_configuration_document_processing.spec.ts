import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Configuration - Document Processing",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto(
      "http://localhost:3000/admin/configuration/document-processing"
    );
    await expect(page.locator("h1.text-3xl")).toHaveText("Document Processing");
    await expect(page.locator("h3.text-2xl")).toHaveText(
      "Process with Unstructured API"
    );
  }
);
