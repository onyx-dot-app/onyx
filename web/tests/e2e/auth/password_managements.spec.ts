import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser, loginAs } from "../utils/auth";
import { TEST_ADMIN2_CREDENTIALS, TEST_ADMIN_CREDENTIALS } from "../constants";

// test("User changes password and logs in with new password", async ({

// Skip this test for now
test.skip("User changes password and logs in with new password", async ({
  page,
}) => {
  // Clear browser context before starting the test
  await page.context().clearCookies();
  await page.context().clearPermissions();

  const { email: uniqueEmail, password: initialPassword } =
    await loginAsRandomUser(page);
  const newPassword = "newPassword456!";

  // Navigate to user settings
  await page.click("#onyx-user-dropdown");
  await page.getByText("User Settings").click();
  await page.getByRole("button", { name: "Password" }).click();

  // Change password
  await page.getByLabel("Current Password").fill(initialPassword);
  await page.getByLabel("New Password", { exact: true }).fill(newPassword);
  await page.getByLabel("Confirm New Password").fill(newPassword);
  await page.getByRole("button", { name: "Change Password" }).click();

  // Verify password change success message
  await expect(page.getByText("Password changed successfully")).toBeVisible();

  // Log out
  await page.getByRole("button", { name: "Close modal", exact: true }).click();
  await page.click("#onyx-user-dropdown");
  await page.getByText("Log out").click();

  // Log in with new password
  await page.goto("http://localhost:3000/auth/login");
  await page.getByTestId("email").fill(uniqueEmail);
  await page.getByTestId("password").fill(newPassword);
  await page.getByRole("button", { name: "Log In" }).click();

  // Verify successful login
  await expect(page).toHaveURL("http://localhost:3000/chat");
  await expect(page.getByText("Explore Assistants")).toBeVisible();
});

test.use({ storageState: "admin2_auth.json" });

// Skip this test for now
test.skip("Admin resets own password and logs in with new password", async ({
  page,
}) => {
  const { email: adminEmail, password: adminPassword } =
    TEST_ADMIN2_CREDENTIALS;
  // Navigate to admin panel
  await page.goto("http://localhost:3000/admin/indexing/status");

  // Check if redirected to login page
  if (page.url().includes("/auth/login")) {
    await loginAs(page, "admin2");
  }

  // Navigate to Users page in admin panel
  await page.goto("http://localhost:3000/admin/users");

  await page.waitForTimeout(500);
  // Find the admin user and click on it
  // Log current URL
  console.log("Current URL:", page.url());
  // Log current rows
  const rows = await page.$$eval("tr", (rows) =>
    rows.map((row) => row.textContent)
  );
  console.log("Current rows:", rows);

  // Log admin email we're looking for
  console.log("Admin email:", adminEmail);

  // Attempt to find and click the row
  await page
    .getByRole("row", { name: adminEmail + " Active" })
    .getByRole("button")
    .click();

  await page.waitForTimeout(500);
  // Reset password
  await page.getByRole("button", { name: "Reset Password" }).click();
  await page.getByRole("button", { name: "Reset Password" }).click();

  // Copy the new password
  const newPasswordElement = page.getByTestId("new-password");
  const newPassword = await newPasswordElement.textContent();
  if (!newPassword) {
    throw new Error("New password not found");
  }

  // Close the modal
  await page.getByLabel("Close modal").click();

  // Log out
  await page.click("#onyx-user-dropdown");
  await page.getByText("Log out").click();

  // Log in with new password
  await page.goto("http://localhost:3000/auth/login");
  await page.getByTestId("email").fill(adminEmail);
  await page.getByTestId("password").fill(newPassword);

  await page.getByRole("button", { name: "Log In" }).click();

  // Verify successful login
  await expect(page).toHaveURL("http://localhost:3000/chat");
  await expect(page.getByText("Explore Assistants")).toBeVisible();
});
