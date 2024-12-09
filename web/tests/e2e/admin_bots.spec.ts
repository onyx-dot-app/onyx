import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Custom Assistants - Slack Bots",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/bots");
    await expect(page.locator("h1.text-3xl")).toHaveText("Slack Bots");
    await expect(page.locator("p.text-sm").nth(0)).toHaveText(
      /^Setup Slack bots that connect to Danswer./
    );
  }
);
