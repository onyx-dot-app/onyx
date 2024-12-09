// ➕ Add this line
import { test, expect, takeSnapshot } from "@chromatic-com/playwright";
import { TEST_CREDENTIALS } from "./constants";

// Then use as normal 👇
test(
  "Homepage",
  {
    tag: "@guest",
  },
  async ({ page }, testInfo) => {
    // Test redirect to login, and redirect to search after login
    const { email, password } = TEST_CREDENTIALS;

    await page.goto("http://localhost:3000/search");

    await page.waitForURL("http://localhost:3000/auth/login?next=%2Fsearch");

    await expect(page).toHaveTitle("Danswer");

    await takeSnapshot(page, "Before login", testInfo);

    await page.fill("#email", email);
    await page.fill("#password", password);

    // Click the login button
    await page.click('button[type="submit"]');

    await page.waitForURL("http://localhost:3000/search");
  }
);
