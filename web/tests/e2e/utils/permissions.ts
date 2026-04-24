import type { Browser, Page } from "@playwright/test";
import { Permission } from "@/lib/types";
import { loginAs } from "./auth";
import { OnyxApiClient } from "./onyxApiClient";
import {
  WORKER_USER_POOL_SIZE,
  workerUserCredentials,
} from "@tests/e2e/constants";

/**
 * Grant permissions to a worker user via a temporary group.
 *
 * In EE mode: creates a group, adds the worker, sets the requested
 * permissions, and returns the group ID (for cleanup).
 *
 * In CE mode: permissions like ADD_AGENTS are auto-granted, so this
 * is a no-op that returns `undefined`.
 *
 * Leaves the page authenticated as admin — callers should clear
 * cookies and re-login as the worker afterwards.
 *
 * Usage:
 * ```ts
 * let permGroupId: number | undefined;
 *
 * test("my test", async ({ page }, testInfo) => {
 *   permGroupId = await grantWorkerPermissions(page, testInfo.workerIndex, [
 *     Permission.ADD_AGENTS,
 *   ]);
 *   await page.context().clearCookies();
 *   await loginAsWorkerUser(page, testInfo.workerIndex);
 *   // ... test body
 * });
 *
 * test.afterAll(async ({ browser }) => {
 *   await cleanupPermissionGroup(browser, permGroupId);
 * });
 * ```
 */
export async function grantWorkerPermissions(
  page: Page,
  workerIndex: number,
  permissions: Permission[]
): Promise<number | undefined> {
  await page.context().clearCookies();
  await loginAs(page, "admin");
  const adminClient = new OnyxApiClient(page.request);

  const registryRes = await page.request.get(
    "/api/manage/admin/permissions/registry"
  );
  // 404 is the expected CE-mode signal that the permission registry is
  // disabled; anything else is a real setup failure we want to surface.
  if (registryRes.status() === 404) return undefined;
  if (!registryRes.ok()) {
    const body = await registryRes.text().catch(() => "");
    throw new Error(
      `Unexpected /manage/admin/permissions/registry status ` +
        `${registryRes.status()}: ${body.slice(0, 200)}`
    );
  }

  const { email } = workerUserCredentials(workerIndex % WORKER_USER_POOL_SIZE);
  const user = await adminClient.getUserByEmail(email);
  if (!user) throw new Error(`Worker user ${email} not found`);

  const groupId = await adminClient.createUserGroup(
    `e2e-perm-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    [user.id]
  );
  await adminClient.setUserGroupPermissions(groupId, permissions);
  return groupId;
}

/**
 * Delete a temporary permission group created by `grantWorkerPermissions`.
 * Safe to call with `undefined` (CE mode no-op).
 */
export async function cleanupPermissionGroup(
  browser: Browser,
  groupId: number | undefined
): Promise<void> {
  if (groupId === undefined) return;
  const context = await browser.newContext({
    storageState: "admin_auth.json",
  });
  const page = await context.newPage();
  const client = new OnyxApiClient(page.request);
  await client
    .deleteUserGroup(groupId)
    .catch((e: unknown) => console.warn("permission group cleanup:", e));
  await context.close();
}
