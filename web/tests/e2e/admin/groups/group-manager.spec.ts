/**
 * E2E Tests: Group Manager assignment & scoped nav
 *
 * Verifies the admin can promote a group member to manager via the per-member
 * shield toggle, and that the promoted manager then reaches the scoped admin
 * groups area — seeing the group they manage but not admin-only actions
 * (New Group / Delete Group).
 */

import { test, expect } from "./fixtures";
import { GroupsAdminPage } from "./GroupsAdminPage";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import {
  workerUserCredentials,
  WORKER_USER_POOL_SIZE,
} from "@tests/e2e/constants";
import type { Browser } from "@playwright/test";

function uniqueGroupName(prefix: string): string {
  return `e2e-${prefix}-${Date.now()}`;
}

/** Best-effort cleanup — logs failures instead of silently swallowing them. */
async function softCleanup(fn: () => Promise<unknown>): Promise<void> {
  await fn().catch((e) => console.warn("cleanup:", e));
}

async function withApiContext(
  browser: Browser,
  fn: (api: OnyxApiClient) => Promise<void>
): Promise<void> {
  const context = await browser.newContext({ storageState: "admin_auth.json" });
  try {
    const api = new OnyxApiClient(context.request);
    await fn(api);
  } finally {
    await context.close();
  }
}

test.describe("Groups page — manager assignment @exclusive", () => {
  let groupId: number;
  let workerEmail: string;
  let workerUserId: string;
  const groupName = uniqueGroupName("mgr");

  test.beforeAll(async ({ browser }, testInfo) => {
    await withApiContext(browser, async (api) => {
      const { email } = workerUserCredentials(
        testInfo.workerIndex % WORKER_USER_POOL_SIZE
      );
      workerEmail = email;
      const user = await api.getUserByEmail(email);
      if (!user) throw new Error(`Worker user ${email} not found`);
      workerUserId = user.id;
      // Create a group with the worker as a member — a manager must be a member.
      groupId = await api.createUserGroup(groupName, [user.id]);
      await api.waitForGroupSync(groupId);
    });
  });

  test.afterAll(async ({ browser }) => {
    await withApiContext(browser, async (api) => {
      await softCleanup(() => api.setGroupManager(groupId, workerUserId, false));
      await softCleanup(() => api.deleteUserGroup(groupId));
    });
  });

  test("admin promotes a member to manager via the toggle", async ({
    groupsPage,
  }) => {
    await groupsPage.gotoEdit(groupId);
    await groupsPage.makeManager(workerEmail);
    // The toggle flips to the revoke affordance once assigned.
    await expect(
      groupsPage.managerToggle(workerEmail, "Revoke manager")
    ).toBeVisible();
  });

  test("a manager sees their managed group without admin-only actions", async ({
    browser,
  }, testInfo) => {
    await withApiContext(browser, (api) =>
      api.setGroupManager(groupId, workerUserId, true)
    );

    const context = await browser.newContext();
    try {
      const page = await context.newPage();
      await loginAsWorkerUser(page, testInfo.workerIndex);
      const managerGroups = new GroupsAdminPage(page);

      // The manager reaches the scoped admin groups area (not redirected).
      await page.goto("/admin/groups");
      await expect(page).toHaveURL(/\/admin\/groups/);
      await managerGroups.expectGroupVisible(groupName);

      // Group creation is admin-only — the New Group action is hidden.
      await expect(managerGroups.newGroupButton).toBeHidden();

      // Opening the managed group: deletion is admin-only — no Delete button.
      await managerGroups.openGroup(groupName);
      await expect(managerGroups.deleteGroupButton).toBeHidden();
    } finally {
      await context.close();
    }
  });
});
