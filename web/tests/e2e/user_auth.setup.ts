import { test as setup, expect } from "@playwright/test";
import { loginAs } from "./utils/auth";

setup("create test user", async ({ page, context }) => {
  // Login as admin
  await loginAs(page, "admin");

  // Create test user
  await page.goto("http://localhost:3000/admin/indexing/status");
  await page.getByRole("button", { name: "Users" }).click();
  await page.getByRole("button", { name: "Invite Users" }).click();
  await page.locator("#emails").click();
  await page.locator("#emails").fill("user_user@test.com");
  await page.getByRole("button", { name: "Add!" }).click();

  // Logout
  await page.getByText("A", { exact: true }).click();
  await page.getByText("Log out").click();

  // Create account for the invited user
  await page.goto("http://localhost:3000/auth/login");
  await page.getByRole("link", { name: "Create an account" }).click();
  await page.getByTestId("email").click();
  await page.waitForTimeout(500);
  await page.getByTestId("email").fill("user_user@test.com");
  await page.waitForTimeout(500);
  await page.getByTestId("password").click();
  await page.waitForTimeout(500);
  await page.getByTestId("password").fill("test");
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: "Sign Up" }).click();
  await page.waitForTimeout(2000);

  // Verify successful account creation
  await page.waitForURL("http://localhost:3000/chat");
  await expect(page).toHaveURL("http://localhost:3000/chat");

  // Save authentication state
  await context.storageState({ path: "user_auth.json" });
});
