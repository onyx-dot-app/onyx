import { Page } from "@playwright/test";
import {
  TEST_ADMIN2_CREDENTIALS,
  TEST_ADMIN_CREDENTIALS,
  TEST_USER_CREDENTIALS,
} from "../constants";

// Basic function which logs in a user (either admin or regular user) to the application
// It handles both successful login attempts and potential timeouts, with a retry mechanism
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

  await page.goto("http://localhost:3000/auth/login", { timeout: 1000 });

  await page.fill("#email", email);
  await page.fill("#password", password);

  // Click the login button
  await page.click('button[type="submit"]');

  try {
    await page.waitForURL("http://localhost:3000/chat", { timeout: 4000 });
  } catch (error) {
    console.log(`Timeout occurred. Current URL: ${page.url()}`);

    // If redirect to /chat doesn't happen, go to /auth/login
    await page.goto("http://localhost:3000/auth/signup", { timeout: 1000 });

    await page.fill("#email", email);
    await page.fill("#password", password);

    // Click the login button
    await page.click('button[type="submit"]');

    try {
      await page.waitForURL("http://localhost:3000/chat", { timeout: 4000 });
    } catch (error) {
      console.log(`Timeout occurred again. Current URL: ${page.url()}`);
    }
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

  await page.goto("http://localhost:3000/auth/signup");

  await page.fill("#email", email);
  await page.fill("#password", password);

  // Click the signup button
  await page.click('button[type="submit"]');
  try {
    await page.waitForURL("http://localhost:3000/chat");
  } catch (error) {
    console.log(`Timeout occurred. Current URL: ${page.url()}`);
    throw new Error("Failed to sign up and redirect to chat page");
  }

  return { email, password };
}

export async function inviteAdmin2AsAdmin1(page: Page) {
  await page.goto("http://localhost:3000/admin/users");
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
      .getByTestId("user-role-dropdown-trigger-admin2_user@test.com")
      .waitFor({ state: "visible", timeout: 5000 });
    await page
      .getByTestId("user-role-dropdown-trigger-admin2_user@test.com")
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
      .getByTestId("user-role-dropdown-trigger-admin2_user@test.com")
      .textContent();
    if (newRole?.toLowerCase().includes("admin")) {
      console.log("Successfully invited admin2 as admin");
    } else {
      throw new Error("Failed to update user role to admin");
    }
  } catch (error) {
    console.error("Error inviting admin2 as admin:", error);
    throw error;
  }
}
