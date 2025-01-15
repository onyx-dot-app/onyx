// dependency for all admin user tests

import { test as setup, expect } from "@playwright/test";
import { TEST_CREDENTIALS } from "./constants";

setup("authenticate", async ({ page }) => {
  const { email, password } = TEST_CREDENTIALS;

  await page.goto("http://localhost:3000/chat");

  await page.waitForURL("http://localhost:3000/auth/login?next=%2Fchat");

  await expect(page).toHaveTitle("Onyx");

  await page.fill("#email", email);
  await page.fill("#password", password);

  // Click the login button
  await page.click('button[type="submit"]');

  await page.waitForURL("http://localhost:3000/chat");

  await page.context().storageState({ path: "admin_auth.json" });
});
