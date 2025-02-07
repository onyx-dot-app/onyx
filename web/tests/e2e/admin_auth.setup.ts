// dependency for all admin user tests
import { test as setup } from "@chromatic-com/playwright";

setup("authenticate as admin", async ({ browser }) => {
  const context = await browser.newContext({ storageState: "admin_auth.json" });
  const page = await context.newPage();
  await page.goto("http://localhost:3000/chat");
  await page.waitForURL("http://localhost:3000/chat");
});
