/**
 * E2E Test: Email Verification Success Flow
 * Tests that the login page displays verification success message when redirected from email verification
 */
import { test, expect } from "@playwright/test";

test("Login page shows verification success message after email verification", async ({
  page,
}) => {
  // Clear cookies so we hit the login page as an unauthenticated user
  await page.context().clearCookies();

  // Navigate to login page with verified=true query param (simulating redirect from email verification)
  await page.goto("/auth/login?verified=true");
  await page.waitForLoadState("networkidle");

  // Verify the success message is visible
  await expect(
    page.getByText("Your email has been verified! Please sign in to continue.")
  ).toBeVisible();

  // Verify normal login page elements are still present
  await expect(page.getByTestId("email")).toBeVisible();
  await expect(page.getByTestId("password")).toBeVisible();
});
