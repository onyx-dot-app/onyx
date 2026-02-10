import type { Locator, Page } from "@playwright/test";
import {
  TEST_ADMIN2_CREDENTIALS,
  TEST_ADMIN_CREDENTIALS,
  TEST_USER_CREDENTIALS,
} from "../constants";
import { logPageState } from "./pageStateLogger";

// Logs in a user (admin, user, or admin2) to the application.
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

  const fillCredentials = async (contextLabel: string) => {
    const emailInput = page.getByTestId("email");
    const passwordInput = page.getByTestId("password");
    await waitForVisible(emailInput, `${contextLabel}: email input`);
    await waitForVisible(passwordInput, `${contextLabel}: password input`);
    await emailInput.fill(email);
    await passwordInput.fill(password);
  };

  console.log(`[loginAs] Navigating to /auth/login as ${userType}`);
  await page.goto("/auth/login");

  // Wait for navigation to settle (login page may redirect to signup if no users exist)
  await page.waitForLoadState("networkidle");

  const currentUrl = page.url();
  const isOnSignup = currentUrl.includes("/auth/signup");
  console.log(
    `[loginAs] After navigation, landed on: ${currentUrl} (isOnSignup: ${isOnSignup})`
  );

  await fillCredentials(
    isOnSignup ? "loginAs signup form" : "loginAs login form"
  );

  // Click the submit button
  await page.click('button[type="submit"]');
  // Log any console errors during login
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      console.log(`[page:console:error] ${msg.text()}`);
    }
  });

  try {
    await page.waitForURL(/\/app.*/, { timeout: 10000 });
    console.log(
      `[loginAs] Redirected to /app for ${userType}. URL: ${page.url()}`
    );
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

  try {
    // Try to fetch current user info from the page context
    const me = await page.evaluate(async () => {
      try {
        const res = await fetch("/api/me", { credentials: "include" });
        return {
          ok: res.ok,
          status: res.status,
          url: res.url,
          body: await res.text(),
        };
      } catch (e) {
        return { ok: false, status: 0, url: "", body: `error: ${String(e)}` };
      }
    });
    console.log(
      `[loginAs] /api/me => ok=${me.ok} status=${me.status} url=${me.url}`
    );
  } catch (e) {
    console.log(`[loginAs] Failed to query /api/me: ${String(e)}`);
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
    // Wait for 2 seconds to ensure the signup process completes
    await page.waitForTimeout(3000);
    // Refresh the page to ensure everything is loaded properly
    // await page.reload();

    await page.waitForURL("/app?new_team=true");
    // Wait for the page to be fully loaded after refresh
    await page.waitForLoadState("networkidle");
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
    console.log("[loginWithCredentials] Skipping authentication");
    return;
  }

  await page.goto("/auth/login");

  // Wait for navigation to settle (login page may redirect to signup if no users exist)
  await page.waitForLoadState("networkidle");

  const currentUrl = page.url();
  const isOnSignup = currentUrl.includes("/auth/signup");
  console.log(
    `[loginWithCredentials] After navigation, landed on: ${currentUrl} (isOnSignup: ${isOnSignup})`
  );

  const emailInput = page.getByTestId("email");
  const passwordInput = page.getByTestId("password");
  await emailInput.waitFor({ state: "visible", timeout: 30000 });
  await emailInput.fill(email);
  await passwordInput.fill(password);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/app.*/, { timeout: 15000 });
}
