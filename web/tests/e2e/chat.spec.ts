import { test, expect } from "@chromatic-com/playwright";

test(
  "Chat",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/chat");
    await expect(page.locator("div.text-2xl").nth(0)).toHaveText("General");
    await expect(page.getByRole("button", { name: "Search S" })).toHaveClass(
      /text-text-application-untoggled/
    );
    await expect(page.getByRole("button", { name: "Chat D" })).toHaveClass(
      /text-text-application-toggled/
    );
  }
);
