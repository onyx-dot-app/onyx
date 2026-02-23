import { test, expect } from "@playwright/test";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";

// These tests exercise the signup (user registration) flow.
// They clear cookies to start unauthenticated, then drive the signup form.

test.describe("Signup flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
  });

  test("Signup page renders correctly", async ({ page }) => {
    await page.goto("/auth/signup");
    await page.waitForLoadState("networkidle");

    // Verify form elements are present
    await expect(page.getByTestId("email")).toBeVisible();
    await expect(page.getByTestId("password")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Create account" })
    ).toBeVisible();

    // Capture the initial signup page
    await expectScreenshot(page, { name: "signup-page-initial" });
  });

  test("User can create a new account", async ({ page }) => {
    // Generate a unique email for this test
    const uniqueEmail = `testuser_${Date.now()}@example.com`;
    const password = "NewUserPassword123!";

    await page.goto("/auth/signup");
    await page.waitForLoadState("networkidle");

    await page.getByTestId("email").fill(uniqueEmail);
    await page.getByTestId("password").fill(password);
    await page.getByRole("button", { name: "Create account" }).click();

    // Should redirect to the app page after successful signup
    await expect(page).toHaveURL(/\/app/, { timeout: 10000 });

    // Verify the session is valid and user is logged in
    const me = await page.request.get("/api/me");
    expect(me.ok()).toBe(true);
    const body = await me.json();
    expect(body.email).toBe(uniqueEmail);
  });

  test("Signup fails with weak password", async ({ page }) => {
    await page.goto("/auth/signup");
    await page.waitForLoadState("networkidle");

    await page.getByTestId("email").fill("newuser@example.com");
    await page.getByTestId("password").fill("weak"); // Too short

    // Trigger validation by blurring the password field
    await page.getByTestId("password").blur();

    // Wait for validation error to appear
    await expect(
      page.getByText(/must be at least 8 characters/i)
    ).toBeVisible();

    // Verify submit button is disabled
    await expect(
      page.getByRole("button", { name: "Create account" })
    ).toBeDisabled();

    // Capture the validation error state
    await expectScreenshot(page, { name: "signup-weak-password-error" });

    // Should stay on the signup page
    await expect(page).toHaveURL(/\/auth\/signup/);
  });

  test("Signup fails with existing email", async ({ page }) => {
    // Use an email that already exists (from global-setup)
    const existingEmail = "admin_user@example.com";

    await page.goto("/auth/signup");
    await page.waitForLoadState("networkidle");

    await page.getByTestId("email").fill(existingEmail);
    await page.getByTestId("password").fill("SomePassword123!");
    await page.getByRole("button", { name: "Create account" }).click();

    // Wait for error message to appear
    await expect(
      page.getByText("An account already exists with the specified email.", {
        exact: true,
      })
    ).toBeVisible();

    // Capture the error state
    await expectScreenshot(page, { name: "signup-existing-email-error" });

    // Should stay on the signup page
    await expect(page).toHaveURL(/\/auth\/signup/);

    // Should not be authenticated as the existing user
    const me = await page.request.get("/api/me");
    expect(me.ok()).toBe(false);
  });

  test("Signup fails with invalid email format", async ({ page }) => {
    await page.goto("/auth/signup");
    await page.waitForLoadState("networkidle");

    await page.getByTestId("email").fill("notavalidemail");
    await page.getByTestId("password").fill("ValidPassword123!");

    // Trigger validation by blurring the email field
    await page.getByTestId("email").blur();

    // Verify submit button is disabled
    await expect(
      page.getByRole("button", { name: "Create account" })
    ).toBeDisabled();

    // Capture the validation error state
    await expectScreenshot(page, { name: "signup-invalid-email-error" });

    // Should stay on the signup page
    await expect(page).toHaveURL(/\/auth\/signup/);
  });

  test("Signup fails with disposable email address", async ({ page }) => {
    // Use a disposable email domain from the fallback list
    const disposableEmail = `testuser_${Date.now()}@mailinator.com`;

    await page.goto("/auth/signup");
    await page.waitForLoadState("networkidle");

    await page.getByTestId("email").fill(disposableEmail);
    await page.getByTestId("password").fill("ValidPassword123!");
    await page.getByRole("button", { name: "Create account" }).click();

    // Wait for error message to appear
    await expect(
      page.getByText("Disposable email addresses are not allowed").first()
    ).toBeVisible();

    // Capture the error state with hidden email to avoid non-deterministic diffs
    await expectScreenshot(page, {
      name: "signup-disposable-email-error",
      mask: ["[data-testid='email']"],
    });

    // Should stay on the signup page
    await expect(page).toHaveURL(/\/auth\/signup/);

    // Should not be authenticated
    const me = await page.request.get("/api/me");
    expect(me.ok()).toBe(false);
  });

  test("Login link navigates to login page", async ({ page }) => {
    await page.goto("/auth/signup");
    await page.waitForLoadState("networkidle");

    // Find and click the login link
    const loginLink = page.getByRole("link", { name: /sign in/i });
    await expect(loginLink).toBeVisible();
    await loginLink.click();

    // Should navigate to login page
    await expect(page).toHaveURL(/\/auth\/login/);
  });
});
