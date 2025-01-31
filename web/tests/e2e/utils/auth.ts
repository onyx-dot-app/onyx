import { Page } from "@playwright/test";
import { TEST_ADMIN_CREDENTIALS, TEST_USER_CREDENTIALS } from "../constants";

// Basic function which logs in a user (either admin or regular user) to the application
// It handles both successful login attempts and potential timeouts, with a retry mechanism
export async function loginAs(page: Page, userType: "admin" | "user") {
  const { email, password } =
    userType === "admin" ? TEST_ADMIN_CREDENTIALS : TEST_USER_CREDENTIALS;
  await page.goto("http://localhost:3000/auth/login", { timeout: 1000 });

  await page.fill("#email", email);
  await page.fill("#password", password);

  // Click the login button
  await page.click('button[type="submit"]');

  try {
    await page.waitForURL("http://localhost:3000/chat", { timeout: 4000 });
  } catch (error) {
    console.log(`Timeout occurred. Current URL: ${page.url()}`);

    // If redirect to /chat doesn't happen, go to /auth/login
    await page.goto("http://localhost:3000/auth/signup", { timeout: 1000 });

    await page.fill("#email", email);
    await page.fill("#password", password);

    // Click the login button
    await page.click('button[type="submit"]');

    try {
      await page.waitForURL("http://localhost:3000/chat", { timeout: 4000 });
    } catch (error) {
      console.log(`Timeout occurred again. Current URL: ${page.url()}`);
    }
  }
}
