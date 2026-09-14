import type { Browser } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { Permission } from "@/lib/types";

async function asAdmin<T>(
  browser: Browser,
  fn: (api: OnyxApiClient) => Promise<T>
): Promise<T> {
  const context = await browser.newContext({
    storageState: "admin_auth.json",
  });
  try {
    return await fn(new OnyxApiClient(context.request));
  } finally {
    await context.close();
  }
}

/** EE grants ADD_AGENTS only through a group, so a fresh user's New Agent
 *  button stays disabled until this runs. Returns the group id to clean up. */
export async function grantAddAgents(
  browser: Browser,
  email: string
): Promise<number> {
  return asAdmin(browser, async (api) => {
    const user = await api.getUserByEmail(email);
    if (!user) throw new Error(`grantAddAgents: no user record for ${email}`);
    const groupId = await api.createUserGroup(
      `e2e-add-agents-${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
      [user.id]
    );
    await api.setUserGroupPermissions(groupId, [Permission.ADD_AGENTS]);
    return groupId;
  });
}

/** Tear down the groups grantAddAgents created; they would otherwise pile up in
 *  the admin user-group table, one per test. */
export async function deleteGrantGroups(
  browser: Browser,
  groupIds: number[]
): Promise<void> {
  if (groupIds.length === 0) return;
  await asAdmin(browser, async (api) => {
    for (const groupId of groupIds) {
      await api.deleteUserGroup(groupId);
    }
  });
}
