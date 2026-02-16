import { test, expect } from "@playwright/test";
import { TEST_ADMIN_CREDENTIALS, TEST_USER_CREDENTIALS } from "../constants";
import { expectScreenshot } from "../utils/visualRegression";

// These tests exercise the browser login UI.
// They clear cookies to start unauthenticated, then drive the login form.

test.describe("Login flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
  });

  test("Login page renders email and password fields", async ({ page }) => {
    await page.goto("/auth/login");
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("email")).toBeVisible();
    await expect(page.getByTestId("password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign In" })).toBeVisible();

    // Capture the login page UI
    await expectScreenshot(page, { name: "login-page-initial" });
  });

  test("User can log in with valid credentials", async ({ page }) => {
    const { email, password } = TEST_ADMIN_CREDENTIALS;

    await page.goto("/auth/login");
    await page.waitForLoadState("networkidle");

    await page.getByTestId("email").fill(email);
    await page.getByTestId("password").fill(password);
    await page.getByRole("button", { name: "Sign In" }).click();

    await expect(page).toHaveURL(/\/app/);

    // Verify the session is valid
    const me = await page.request.get("/api/me");
    expect(me.ok()).toBe(true);
    const body = await me.json();
    expect(body.email).toBe(email);
  });

  test("Login fails with invalid password", async ({ page }) => {
    await page.goto("/auth/login");
    await page.waitForLoadState("networkidle");

    await page.getByTestId("email").fill(TEST_USER_CREDENTIALS.email);
    await page.getByTestId("password").fill("WrongPassword123!");
    await page.getByRole("button", { name: "Sign In" }).click();

    // Wait for error message to appear (use exact match to avoid duplicate selector)
    await expect(
      page.getByText("Invalid email or password", { exact: true })
    ).toBeVisible();

    // Capture the error state
    await expectScreenshot(page, { name: "login-invalid-password-error" });

    // Should stay on the login page
    await expect(page).toHaveURL(/\/auth\/login/);

    // Should not be authenticated
    const me = await page.request.get("/api/me");
    expect(me.ok()).toBe(false);
  });

  test("Login fails with non-existent user", async ({ page }) => {
    await page.goto("/auth/login");
    await page.waitForLoadState("networkidle");

    await page.getByTestId("email").fill("nonexistent@example.com");
    await page.getByTestId("password").fill("SomePassword123!");
    await page.getByRole("button", { name: "Sign In" }).click();

    // Wait for error message to appear (use exact match to avoid duplicate selector)
    await expect(
      page.getByText("Invalid email or password", { exact: true })
    ).toBeVisible();

    // Capture the error state
    await expectScreenshot(page, { name: "login-nonexistent-user-error" });

    // Should stay on the login page
    await expect(page).toHaveURL(/\/auth\/login/);
  });
});
