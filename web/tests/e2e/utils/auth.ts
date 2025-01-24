import { Page } from "@playwright/test";
import { TEST_CREDENTIALS, TEST_USER_CREDENTIALS } from "../constants";

export async function loginAs(page: Page, userType: "admin" | "user") {
  const { email, password } =
    userType === "admin" ? TEST_CREDENTIALS : TEST_USER_CREDENTIALS;

  await page.goto("http://localhost:3000/chat");

  await page.waitForURL("http://localhost:3000/auth/login?next=%2Fchat");

  await page.fill("#email", email);
  await page.fill("#password", password);

  // Click the login button
  await page.click('button[type="submit"]');

  // Log the entire page contents after login
  console.log("Page contents after login:", await page.content());

  await page.waitForURL("http://localhost:3000/chat");
}
