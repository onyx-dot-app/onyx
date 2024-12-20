import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Custom Assistants - Assistants",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/assistants");
    await expect(page.locator("h1.text-3xl")).toHaveText("Assistants");
    await expect(page.locator("p.text-sm").nth(0)).toHaveText(
      /^Assistants are a way to build/
    );

    const generalTextLocator = page.locator("tr.border-b td").nth(1);
    await expect(generalTextLocator.locator("p.text")).toHaveText("General");
  }
);
