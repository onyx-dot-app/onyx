import type { Locator, Page } from "@playwright/test";
import {
  TEST_ADMIN2_CREDENTIALS,
  TEST_ADMIN_CREDENTIALS,
  TEST_USER_CREDENTIALS,
} from "../constants";
import { logPageState } from "./pageStateLogger";

// Logs in a user (admin, user, or admin2) via the browser UI.
// Users must already be provisioned (see global-setup.ts).
export async function loginAs(
  page: Page,
  userType: "admin" | "user" | "admin2"
) {
  const { email, password } =
    userType === "admin"
      ? TEST_ADMIN_CREDENTIALS
      : userType === "admin2"
        ? TEST_ADMIN2_CREDENTIALS
        : TEST_USER_CREDENTIALS;

  const waitForVisible = async (
    locator: Locator,
    debugContext: string,
    timeoutMs = 30000
  ) => {
    try {
      await locator.waitFor({ state: "visible", timeout: timeoutMs });
    } catch (error) {
      await logPageState(page, debugContext, "[login-debug]");
      throw error;
    }
  };

  await page.goto("/auth/login");
  await page.waitForLoadState("networkidle");

  const isOnSignup = page.url().includes("/auth/signup");
  const contextLabel = isOnSignup
    ? "loginAs signup form"
    : "loginAs login form";

  const emailInput = page.getByTestId("email");
  const passwordInput = page.getByTestId("password");
  await waitForVisible(emailInput, `${contextLabel}: email input`);
  await waitForVisible(passwordInput, `${contextLabel}: password input`);
  await emailInput.fill(email);
  await passwordInput.fill(password);

  await page.click('button[type="submit"]');

  try {
    await page.waitForURL(/\/app.*/, { timeout: 10000 });
  } catch {
    await logPageState(
      page,
      `[loginAs] Timeout waiting for /app redirect (${userType}). URL: ${page.url()}`,
      "[login-debug]"
    );
    throw new Error(
      `[loginAs] Failed to login as ${userType}. Current URL: ${page.url()}`
    );
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

  await page.goto("/auth/signup");

  const emailInput = page.getByTestId("email");
  const passwordInput = page.getByTestId("password");
  await emailInput.waitFor({ state: "visible", timeout: 30000 });
  await emailInput.fill(email);
  await passwordInput.fill(password);

  // Click the signup button
  await page.click('button[type="submit"]');
  try {
    await page.waitForURL(/\/(app|chat)(\?.*)?$/, { timeout: 30000 });
    await page.waitForLoadState("domcontentloaded");
  } catch {
    console.log(`Timeout occurred. Current URL: ${page.url()}`);
    throw new Error("Failed to sign up and redirect to app page");
  }

  return { email, password };
}

export async function loginWithCredentials(
  page: Page,
  email: string,
  password: string
) {
  if (process.env.SKIP_AUTH === "true") {
    return;
  }

  await page.goto("/auth/login");
  await page.waitForLoadState("networkidle");

  const emailInput = page.getByTestId("email");
  const passwordInput = page.getByTestId("password");
  await emailInput.waitFor({ state: "visible", timeout: 30000 });
  await emailInput.fill(email);
  await passwordInput.fill(password);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/app.*/, { timeout: 15000 });
}
