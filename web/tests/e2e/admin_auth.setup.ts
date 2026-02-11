// dependency for all admin user tests
import { test as setup } from "@playwright/test";

setup("authenticate as admin", async ({ browser }) => {
  const context = await browser.newContext({ storageState: "admin_auth.json" });
  const page = await context.newPage();
  await page.goto("/app");
  await page.waitForURL("/app");
});
