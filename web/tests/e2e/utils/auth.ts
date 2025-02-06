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
// Function to generate a random email and password
const generateRandomCredentials = () => {
  const randomString = Math.random().toString(36).substring(2, 10);
  const specialChars = "!@#$%^&*()_+{}[]|:;<>,.?~";
  const randomSpecialChar =
    specialChars[Math.floor(Math.random() * specialChars.length)];
  const randomUpperCase = String.fromCharCode(
    65 + Math.floor(Math.random() * 26)
  );
  const randomNumber = Math.floor(Math.random() * 10);

  return {
    email: `test_${randomString}@example.com`,
    password: `P@ssw0rd_${randomUpperCase}${randomSpecialChar}${randomNumber}${randomString}`,
  };
};

// Function to sign up a new random user
export async function loginAsRandomUser(page: Page) {
  const { email, password } = generateRandomCredentials();

  await page.goto("http://localhost:3000/auth/signup");

  await page.fill("#email", email);
  await page.fill("#password", password);

  // Click the signup button
  await page.click('button[type="submit"]');
  try {
    await page.waitForURL("http://localhost:3000/chat");
  } catch (error) {
    console.log(`Timeout occurred. Current URL: ${page.url()}`);
    throw new Error("Failed to sign up and redirect to chat page");
  }

  return { email, password };
}
