/**
 * Playwright fixtures for Admin Users page tests.
 *
 * Provides:
 * - Authenticated admin page
 * - OnyxApiClient for API-level setup/teardown
 * - UsersAdminPage page object
 */

import { test as base, expect, type Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { UsersAdminPage } from "./UsersAdminPage";

export const test = base.extend<{
  adminPage: Page;
  api: OnyxApiClient;
  usersPage: UsersAdminPage;
}>({
  adminPage: async ({ page }, use) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await use(page);
  },

  api: async ({ adminPage }, use) => {
    const client = new OnyxApiClient(adminPage.request);
    await use(client);
  },

  usersPage: async ({ adminPage }, use) => {
    const usersPage = new UsersAdminPage(adminPage);
    await use(usersPage);
  },
});

export { expect };
