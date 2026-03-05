import type { Page } from "@playwright/test";
import {
  TEST_ADMIN2_CREDENTIALS,
  TEST_ADMIN_CREDENTIALS,
  WORKER_USER_POOL_SIZE,
  workerUserCredentials,
} from "@tests/e2e/constants";

/**
 * Log in via the API and set cookies on the page's browser context.
 * Much faster than navigating through the login UI.
 */
export async function apiLogin(
  page: Page,
  email: string,
  password: string
): Promise<void> {
  const res = await page.request.post("/api/auth/login", {
    form: { username: email, password },
  });
  if (!res.ok()) {
    const body = await res.text();
    throw new Error(`API login failed for ${email}: ${res.status()} ${body}`);
  }
}

// Logs in a known test user (admin or admin2) via the API.
// Users must already be provisioned (see global-setup.ts).
export async function loginAs(
  page: Page,
  userType: "admin" | "admin2"
): Promise<void> {
  const { email, password } =
    userType === "admin" ? TEST_ADMIN_CREDENTIALS : TEST_ADMIN2_CREDENTIALS;

  await apiLogin(page, email, password);
}

/**
 * Log in as a worker-specific user for test isolation.
 * Uses modulo to map any workerIndex (which can exceed the pool size due to
 * retries spawning new workers) back to a provisioned user. This is safe
 * because retries never run in parallel with the original attempt.
 */
export async function loginAsWorkerUser(
  page: Page,
  workerIndex: number
): Promise<void> {
  const { email, password } = workerUserCredentials(
    workerIndex % WORKER_USER_POOL_SIZE
  );
  await apiLogin(page, email, password);
}

// Generate a random email and password for throwaway test users.
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

// Register and log in as a new random user via the API.
export async function loginAsRandomUser(page: Page): Promise<{
  email: string;
  password: string;
}> {
  const { email, password } = generateRandomCredentials();

  const registerRes = await page.request.post("/api/auth/register", {
    data: { email, username: email, password },
  });
  if (!registerRes.ok()) {
    const body = await registerRes.text();
    throw new Error(
      `Failed to register random user ${email}: ${registerRes.status()} ${body}`
    );
  }

  await apiLogin(page, email, password);

  // Navigate to the app so the page is ready for test interactions
  await page.goto("/app?new_team=true");
  await page.waitForLoadState("networkidle");

  return { email, password };
}
