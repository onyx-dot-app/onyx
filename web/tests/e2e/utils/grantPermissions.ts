import type { Browser } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { Permission } from "@/lib/types";

/** EE grants ADD_AGENTS only through a group, so a fresh user's New Agent
 *  button stays disabled until this runs. */
export async function grantAddAgents(
  browser: Browser,
  email: string
): Promise<void> {
  const context = await browser.newContext({
    storageState: "admin_auth.json",
  });
  try {
    const api = new OnyxApiClient(context.request);
    const user = await api.getUserByEmail(email);
    if (!user) throw new Error(`grantAddAgents: no user record for ${email}`);
    const groupId = await api.createUserGroup(
      `e2e-add-agents-${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
      [user.id]
    );
    await api.setUserGroupPermissions(groupId, [Permission.ADD_AGENTS]);
  } finally {
    await context.close();
  }
}
