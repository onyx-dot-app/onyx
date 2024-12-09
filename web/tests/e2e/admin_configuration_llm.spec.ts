import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Configuration - LLM",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/configuration/llm");
    await expect(page.locator("h1.text-3xl")).toHaveText("LLM Setup");
    await expect(page.locator("h1.text-lg").nth(0)).toHaveText(
      "Enabled LLM Providers"
    );
  }
);
