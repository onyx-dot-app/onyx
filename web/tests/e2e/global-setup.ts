import { chromium, FullConfig } from "@playwright/test";
import { loginAs } from "./utils/auth";

async function globalSetup(config: FullConfig) {
  const browser = await chromium.launch();

  // Setup admin auth
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await loginAs(adminPage, "admin");
  await adminContext.storageState({ path: "admin_auth.json" });
  await adminContext.close();

  // Setup user auth
  const userContext = await browser.newContext();
  const userPage = await userContext.newPage();

  // Login as admin to create user
  await loginAs(userPage, "admin");
  await userPage.goto("/admin/indexing/status");
  await userPage.getByRole("button", { name: "Users" }).click();
  await userPage.getByRole("button", { name: "Invite Users" }).click();
  await userPage.locator("#emails").fill("user_user@test.com");
  await userPage.getByRole("button", { name: "Add!" }).click();

  // Logout admin
  await userPage.getByText("A", { exact: true }).click();
  await userPage.getByText("Log out").click();

  // Create and login as new user
  await userPage.goto("/auth/login");
  await userPage.getByRole("link", { name: "Create an account" }).click();
  await userPage.getByTestId("email").fill("user_user@test.com");
  await userPage.getByTestId("password").fill("test");
  await userPage.getByRole("button", { name: "Sign Up" }).click();
  await userPage.waitForURL("/chat");

  await userContext.storageState({ path: "user_auth.json" });
  await userContext.close();

  await browser.close();
}

export default globalSetup;
