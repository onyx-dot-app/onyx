import { chromium, FullConfig } from "@playwright/test";
import { loginAs } from "./utils/auth";

async function globalSetup(config: FullConfig) {
  const browser = await chromium.launch();

  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await loginAs(adminPage, "admin");
  await adminContext.storageState({ path: "admin_auth.json" });
  await adminContext.close();

  const userContext = await browser.newContext();
  const userPage = await userContext.newPage();
  await loginAs(userPage, "user");
  await userContext.storageState({ path: "user_auth.json" });
  await userContext.close();

  await browser.close();
}

export default globalSetup;
