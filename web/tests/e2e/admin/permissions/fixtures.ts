import { test as base, expect, type Page } from "@playwright/test";
import { loginAs, apiLogin } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const TEST_PASSWORD = "PermGating123!";

function uniqueId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export interface TestUserContext {
  userId: string;
  groupId: number;
  email: string;
  password: string;
}

async function softCleanup(fn: () => Promise<unknown>): Promise<void> {
  await fn().catch((e) => console.warn("cleanup:", e));
}

export const test = base.extend<{
  adminClient: OnyxApiClient;
  testUserContext: TestUserContext;
}>({
  adminClient: async ({ page }, use) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await use(new OnyxApiClient(page.request));
  },

  testUserContext: async ({ page }, use) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const adminClient = new OnyxApiClient(page.request);

    const email = `e2e-perm-gating-${uniqueId("user")}@example.com`;
    const groupName = `e2e-perm-gating-${uniqueId("group")}`;
    let userId: string | undefined;
    let groupId: number | undefined;

    try {
      const user = await adminClient.registerUser(email, TEST_PASSWORD);
      userId = user.id;
      groupId = await adminClient.createUserGroup(groupName, [userId]);

      await use({ userId, groupId, email, password: TEST_PASSWORD });
    } finally {
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanup = new OnyxApiClient(page.request);

      if (groupId !== undefined) {
        await softCleanup(() => cleanup.deleteUserGroup(groupId!));
      }
      await softCleanup(() => cleanup.deactivateUser(email));
      await softCleanup(() => cleanup.deleteUser(email));
    }
  },
});

export { expect };
