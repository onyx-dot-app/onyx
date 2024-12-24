import { test as base, expect, Page, BrowserContext } from "@playwright/test";

type AuthFixture = {
  auth: (
    role: "admin" | "user"
  ) => Promise<{ context: BrowserContext; page: Page }>;
};

export const test = base.extend<AuthFixture>({
  auth: async ({ browser, contextOptions }, use) => {
    await use(async (role: "admin" | "user") => {
      const context = await browser.newContext({
        ...contextOptions, // Inherit all context options, including 'headless'
        storageState: role === "admin" ? "admin_auth.json" : "user_auth.json",
      });
      const page = await context.newPage();
      return { context, page };
    });
  },
});

export { expect };
