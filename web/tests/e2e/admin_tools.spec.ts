import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - Custom Assistants - Tools",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/tools");
    await expect(page.locator("h1.text-3xl")).toHaveText("Tools");
    await expect(page.locator("p.text-sm")).toHaveText(
      "Tools allow assistants to retrieve information or take actions."
    );
  }
);
