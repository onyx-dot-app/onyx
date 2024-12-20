import { test, expect } from "@chromatic-com/playwright";

test(
  "Chat",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    // Test simple loading
    await page.goto("http://localhost:3000/chat");

    // Check for the "General" text in the new UI element
    await expect(
      page.locator("div.flex.items-center span.font-bold")
    ).toHaveText("General");

    // Check for the presence of the new UI element
    await expect(
      page.locator("div.flex.justify-center div.bg-black.rounded-full")
    ).toBeVisible();

    // Check for the SVG icon
    await expect(
      page.locator("div.flex.justify-center svg.w-5.h-5")
    ).toBeVisible();
  }
);
