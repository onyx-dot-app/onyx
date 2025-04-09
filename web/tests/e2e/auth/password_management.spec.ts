import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser, loginAs } from "../utils/auth";
import { TEST_ADMIN2_CREDENTIALS, TEST_ADMIN_CREDENTIALS } from "../constants";

// test("User changes password and logs in with new password", async ({

// Skip this test for now
// test("User changes password and logs in with new password", async ({
//   page,
// }) => {
//   console.log("Starting password change test");
//   // Clear browser context before starting the test
//   await page.context().clearCookies();
//   await page.context().clearPermissions();

//   const { email: uniqueEmail, password: initialPassword } =
//     await loginAsRandomUser(page);
//   console.log(`Logged in as random user: ${uniqueEmail}`);
//   const newPassword = "newPassword456!";

//   // Navigate to user settings
//   console.log("Navigating to user settings");
//   await page.click("#onyx-user-dropdown");
//   await page.getByText("User Settings").click();
//   await page.getByRole("button", { name: "Password" }).click();

//   // Change password
//   console.log("Changing password");
//   await page.getByLabel("Current Password").fill(initialPassword);
//   await page.getByLabel("New Password", { exact: true }).fill(newPassword);
//   await page.getByLabel("Confirm New Password").fill(newPassword);
//   await page.getByRole("button", { name: "Change Password" }).click();

//   // Verify password change success message
//   console.log("Verifying password change success");
//   await expect(page.getByText("Password changed successfully")).toBeVisible();

//   // Log out
//   console.log("Logging out");
//   await page.getByRole("button", { name: "Close modal", exact: true }).click();
//   await page.click("#onyx-user-dropdown");
//   await page.getByText("Log out").click();

//   // Log in with new password
//   console.log("Logging in with new password");
//   await page.goto("http://localhost:3000/auth/login");
//   await page.getByTestId("email").fill(uniqueEmail);
//   await page.getByTestId("password").fill(newPassword);
//   await page.getByRole("button", { name: "Log In" }).click();

//   // Verify successful login
//   console.log("Verifying successful login");
//   await expect(page).toHaveURL("http://localhost:3000/chat");
//   await expect(page.getByText("Explore Assistants")).toBeVisible();

//   // Reset password back to initial password
//   console.log("Resetting password back to initial password");
//   await page.click("#onyx-user-dropdown");
//   await page.getByText("User Settings").click();
//   await page.getByRole("button", { name: "Password" }).click();

//   // Change password back to original
//   console.log("Changing password back to original");
//   await page.getByLabel("Current Password").fill(newPassword);
//   await page.getByLabel("New Password", { exact: true }).fill(initialPassword);
//   await page.getByLabel("Confirm New Password").fill(initialPassword);
//   await page.getByRole("button", { name: "Change Password" }).click();

//   // Verify password change success message
//   console.log("Verifying final password change success");
//   await expect(page.getByText("Password changed successfully")).toBeVisible();
// });

test.use({ storageState: "admin2_auth.json" });

// Skip this test for now
test("Admin resets own password and logs in with new password", async ({
  page,
}) => {
  console.log("Starting admin password reset test");
  const { email: adminEmail, password: adminPassword } =
    TEST_ADMIN2_CREDENTIALS;
  console.log(`Admin email to test: ${adminEmail}`);

  // Navigate to admin panel
  console.log("Navigating to admin panel");
  await page.goto("http://localhost:3000/admin/indexing/status");
  console.log("Current URL after navigation:", await page.url());

  // Check if redirected to login page
  if (page.url().includes("/auth/login")) {
    console.log("Redirected to login page, logging in as admin2");
    await loginAs(page, "admin2");
  }

  // Navigate to Users page in admin panel
  console.log("Navigating to Users page in admin panel");
  await page.goto("http://localhost:3000/admin/users");
  console.log("Current URL after navigation to users page:", await page.url());

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
  console.log("Admin email we're looking for:", adminEmail);

  // Attempt to find and click the row
  console.log("Attempting to find and click the admin user row");
  await page
    .getByRole("row", { name: adminEmail + " Active" })
    .getByRole("button")
    .click();
  console.log("Clicked on admin user row");

  await page.waitForTimeout(500);
  // Reset password
  console.log("Resetting password");
  await page.getByRole("button", { name: "Reset Password" }).click();
  await page.getByRole("button", { name: "Reset Password" }).click();
  console.log("Password reset confirmed");

  // Copy the new password
  console.log("Getting new password");
  await page.waitForTimeout(20000); // Wait for 20 seconds
  const newPasswordElement = page.getByTestId("new-password");
  const newPassword = await newPasswordElement.textContent();
  if (!newPassword) {
    throw new Error("New password not found");
  }
  console.log("New password retrieved (not logging actual password)");

  // Close the modal
  console.log("Closing modal");
  await page.getByLabel("Close modal").click();

  // Log out
  console.log("Logging out");
  await page.reload();
  await page.waitForLoadState("networkidle");
  await page.click("#onyx-user-dropdown");
  await page.getByText("Log out").click();

  // Log in with new password
  console.log("Logging in with new password");
  await page.goto("http://localhost:3000/auth/login");
  await page.getByTestId("email").fill(adminEmail);
  await page.getByTestId("password").fill(newPassword);

  await page.getByRole("button", { name: "Log In" }).click();

  // Verify successful login
  console.log("Verifying successful login");
  await expect(page).toHaveURL("http://localhost:3000/chat");
  await expect(page.getByText("Explore Assistants")).toBeVisible();

  // Reset password back to original admin password
  console.log("Resetting password back to original admin password");
  await page.click("#onyx-user-dropdown");
  await page.getByText("User Settings").click();
  await page.getByRole("button", { name: "Password" }).click();

  // Change password back to original
  console.log("Changing password back to original");
  await page.getByLabel("Current Password").fill(newPassword);
  await page.getByLabel("New Password", { exact: true }).fill(adminPassword);
  await page.getByLabel("Confirm New Password").fill(adminPassword);
  await page.getByRole("button", { name: "Change Password" }).click();

  // Verify password change success message
  console.log("Verifying final password change success");
  await expect(page.getByText("Password changed successfully")).toBeVisible();
});
