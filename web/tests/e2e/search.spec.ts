import { test, expect } from "@chromatic-com/playwright";

test(
  "Search",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/search");
    await expect(page.locator("div.text-3xl")).toHaveText("Unlock Knowledge");
    await expect(page.getByRole("button", { name: "Search S" })).toHaveClass(
      /text-text-application-toggled/
    );
    await expect(page.getByRole("button", { name: "Chat D" })).toHaveClass(
      /text-text-application-untoggled/
    );
  }
);
