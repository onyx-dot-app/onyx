import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Custom Assistants - Prompt Library",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/prompt-library");
    await expect(page.locator("h1.text-3xl")).toHaveText("Prompt Library");
    await expect(page.locator("p.text-sm")).toHaveText(
      /^Create prompts that can be accessed/
    );
  }
);
