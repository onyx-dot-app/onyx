import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Custom Assistants - Standard Answers",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/standard-answer");
    await expect(page.locator("h1.text-3xl")).toHaveText("Standard Answers");
    await expect(page.locator("p.text-sm").nth(0)).toHaveText(
      /^Manage the standard answers for pre-defined questions./
    );
  }
);
