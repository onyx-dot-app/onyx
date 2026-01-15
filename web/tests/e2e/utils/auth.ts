import type { Locator, Page } from "@playwright/test";
import {
  TEST_ADMIN2_CREDENTIALS,
  TEST_ADMIN_CREDENTIALS,
  TEST_USER_CREDENTIALS,
} from "../constants";
import { logPageState } from "./pageStateLogger";

// Basic function which logs in a user (either admin or regular user) to the application
// It handles both successful login attempts and potential timeouts, with a retry mechanism
export async function loginAs(
  page: Page,
  userType: "admin" | "user" | "admin2"
) {
  // Skip authentication if SKIP_AUTH environment variable is set
  if (process.env.SKIP_AUTH === "true") {
    console.log(
      `[loginAs] Skipping authentication for ${userType} (SKIP_AUTH=true)`
    );
    return;
  }

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

  await fillCredentials("loginAs primary form");

  // Click the login button
  await page.click('button[type="submit"]');
  // Log any console errors during login
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      console.log(`[page:console:error] ${msg.text()}`);
    }
  });

  try {
    await page.waitForURL("/chat", { timeout: 10000 });
    console.log(
      `[loginAs] Redirected to /chat for ${userType}. URL: ${page.url()}`
    );
  } catch {
    console.log(`[loginAs] Timeout to /chat. Current URL: ${page.url()}`);

    // If redirect to /chat doesn't happen, go to /auth/login
    console.log(`[loginAs] Navigating to /auth/signup as fallback`);
    await page.goto("/auth/signup");
    await logPageState(
      page,
      `[loginAs] Landed on /auth/signup fallback (${userType})`,
      "[login-debug]"
    );

    await fillCredentials("loginAs fallback form");

    // Click the login button
    await page.click('button[type="submit"]');

    try {
      await page.waitForURL("/chat", { timeout: 10000 });
      console.log(
        `[loginAs] Fallback redirected to /chat for ${userType}. URL: ${page.url()}`
      );
    } catch {
      console.log(
        `[loginAs] Fallback timeout again. Current URL: ${page.url()}`
      );
    }
  }

  try {
    // Try to fetch current user info from the page context
    const me = await page.evaluate(async () => {
      try {
        const res = await fetch("/api/auth/me", { credentials: "include" });
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
      `[loginAs] /api/auth/me => ok=${me.ok} status=${me.status} url=${me.url}`
    );
  } catch (e) {
    console.log(`[loginAs] Failed to query /api/auth/me: ${String(e)}`);
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
  // Skip authentication if SKIP_AUTH environment variable is set
  if (process.env.SKIP_AUTH === "true") {
    console.log("[loginAsRandomUser] Skipping authentication (SKIP_AUTH=true)");
    return { email: "skipped@local.test", password: "skipped" };
  }

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

    await page.waitForURL("/chat?new_team=true");
    // Wait for the page to be fully loaded after refresh
    await page.waitForLoadState("networkidle");
  } catch {
    console.log(`Timeout occurred. Current URL: ${page.url()}`);
    throw new Error("Failed to sign up and redirect to chat page");
  }

  return { email, password };
}

export async function inviteAdmin2AsAdmin1(page: Page) {
  await page.goto("/admin/users");
  // Wait for 400ms to ensure the page has loaded completely
  await page.waitForTimeout(400);

  // Log all currently visible test ids
  const testIds = await page.evaluate(() => {
    return Array.from(document.querySelectorAll("[data-testid]")).map((el) =>
      el.getAttribute("data-testid")
    );
  });
  console.log("Currently visible test ids:", testIds);

  try {
    // Wait for the dropdown trigger to be visible and click it
    await page
      .getByTestId("user-role-dropdown-trigger-admin2_user@example.com")
      .waitFor({ state: "visible", timeout: 5000 });
    await page
      .getByTestId("user-role-dropdown-trigger-admin2_user@example.com")
      .click();

    // Wait for the admin option to be visible
    await page
      .getByTestId("user-role-dropdown-admin")
      .waitFor({ state: "visible", timeout: 5000 });

    // Click the admin option
    await page.getByTestId("user-role-dropdown-admin").click();

    // Wait for any potential loading or update to complete
    await page.waitForTimeout(1000);

    // Verify that the change was successful (you may need to adjust this based on your UI)
    const newRole = await page
      .getByTestId("user-role-dropdown-trigger-admin2_user@example.com")
      .textContent();
    if (newRole?.toLowerCase().includes("admin")) {
      console.log("Successfully invited admin2 as admin");
    } else {
      throw new Error("Failed to update user role to admin");
    }
  } catch (error: unknown) {
    console.error("Error inviting admin2 as admin:", error);
    throw error;
  }
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
  const emailInput = page.getByTestId("email");
  const passwordInput = page.getByTestId("password");
  await emailInput.waitFor({ state: "visible", timeout: 30000 });
  await emailInput.fill(email);
  await passwordInput.fill(password);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/chat.*/, { timeout: 15000 });
}
