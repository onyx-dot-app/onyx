import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - User Management - Token Rate Limits",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/admin/token-rate-limits");
    await expect(page.locator("h1.text-3xl")).toHaveText("Token Rate Limits");
    await expect(page.locator("p.text-sm").nth(0)).toHaveText(
      /^Token rate limits enable you control how many tokens can be spent in a given time period./
    );
    await expect(
      page.getByRole("button", { name: "Create a Token Rate Limit" })
    ).toHaveCount(1);
    await expect(page.locator("h1.text-lg")).toHaveText(
      "Global Token Rate Limits"
    );
  }
);
