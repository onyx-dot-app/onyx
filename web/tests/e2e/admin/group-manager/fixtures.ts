import { test as base, expect, type APIResponse } from "@playwright/test";
import { loginAs, apiLogin } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const TEST_PASSWORD = "ScopedManager123!";

function uniqueId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function softCleanup(fn: () => Promise<unknown>): Promise<void> {
  await fn().catch((e) => console.warn("cleanup:", e));
}

export interface ScopedManagerContext {
  userId: string;
  groupId: number;
  groupName: string;
  email: string;
  password: string;
}

export const test = base.extend<{
  adminClient: OnyxApiClient;
  scopedManager: ScopedManagerContext;
}>({
  adminClient: async ({ page }, use) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await use(new OnyxApiClient(page.request));
  },

  // A scoped manager holds no global permission — authority is the is_manager edge
  // alone, so the promotion is the whole setup.
  scopedManager: async ({ page }, use) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const adminClient = new OnyxApiClient(page.request);

    const email = `e2e-scoped-mgr-${uniqueId("user")}@example.com`;
    const groupName = `e2e-scoped-mgr-${uniqueId("group")}`;
    let userId: string | undefined;
    let groupId: number | undefined;

    try {
      const user = await adminClient.registerUser(email, TEST_PASSWORD);
      userId = user.id;
      groupId = await adminClient.createUserGroup(groupName, [userId]);
      await adminClient.waitForGroupSync(groupId);
      await adminClient.setGroupManager(groupId, userId);

      await use({ userId, groupId, groupName, email, password: TEST_PASSWORD });
    } finally {
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanup = new OnyxApiClient(page.request);

      if (groupId !== undefined) {
        // a group with connectors still attached refuses deletion
        await softCleanup(() =>
          cleanup.setGroupCcPairs(groupId!, groupName, [], {
            waitForSync: false,
          })
        );
        await softCleanup(() => cleanup.deleteUserGroup(groupId!));
      }
      await softCleanup(() => cleanup.deactivateUser(email));
      await softCleanup(() => cleanup.deleteUser(email));
    }
  },
});

/**
 * Everything a scoped manager should and shouldn't be able to act on, seeded once.
 *
 * Each pair is deliberate: an in-scope resource next to an out-of-scope twin, so a
 * page assertion can prove the boundary rather than just that something rendered.
 */
export interface ScopedWorld {
  manager: ScopedManagerContext;
  /** private, in the managed group — manager may edit, may not delete */
  managedCcPairId: number;
  /** the manager's own, detached from every group — may edit AND delete */
  grouplessCcPairId: number;
  /** admin's, in a group the manager doesn't manage — invisible */
  foreignCcPairId: number;
  managedDocSetId: number;
  managedDocSetName: string;
  grouplessDocSetId: number;
  grouplessDocSetName: string;
  /** the manager's own action */
  ownActionId: number;
  /** admin's, reachable because an agent in the managed group uses it */
  connectedActionId: number;
  /** admin's, on no agent — must stay invisible */
  orphanActionId: number;
}

export const worldTest = test.extend<{ world: ScopedWorld }>({
  world: async ({ page, adminClient, scopedManager }, use) => {
    const stamp = Date.now();

    const foreignGroupName = `e2e-scoped-foreign-${stamp}`;
    const foreignGroupId = await adminClient.createUserGroup(foreignGroupName);
    await adminClient.waitForGroupSync(foreignGroupId);

    const orphanActionId = await adminClient.createCustomTool(
      `orphan-action-${stamp}`
    );
    const connectedActionId = await adminClient.createCustomTool(
      `connected-action-${stamp}`
    );
    const foreignCcPairId = await adminClient.createFileConnector(
      `foreign-conn-${stamp}`,
      "private",
      [foreignGroupId]
    );
    // an agent in the managed group is the only path from that group to an action
    await adminClient.createAgent(`bridge-agent-${stamp}`, "", {
      isPublic: false,
      groups: [scopedManager.groupId],
      toolIds: [connectedActionId],
    });

    const managerClient = await actAsManager(page, scopedManager);
    const ownActionId = await managerClient.createCustomTool(
      `own-action-${stamp}`
    );
    const managedCcPairId = await managerClient.createFileConnector(
      `managed-conn-${stamp}`,
      "private",
      [scopedManager.groupId]
    );
    const managedDocSetName = `managed-set-${stamp}`;
    const managedDocSetId = await managerClient.createDocumentSet(
      managedDocSetName,
      [managedCcPairId],
      { isPublic: false, groups: [scopedManager.groupId] }
    );

    // the groupless pair has to start in a group and lose it — creating one
    // directly is refused for having no managed scope
    const grouplessGroupName = `e2e-scoped-tmp-${stamp}`;
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const grouplessGroupId = await adminClient.createUserGroup(
      grouplessGroupName,
      [scopedManager.userId]
    );
    await adminClient.waitForGroupSync(grouplessGroupId);
    await adminClient.setGroupManager(grouplessGroupId, scopedManager.userId);

    const managerClient2 = await actAsManager(page, scopedManager);
    const grouplessCcPairId = await managerClient2.createFileConnector(
      `groupless-conn-${stamp}`,
      "private",
      [grouplessGroupId]
    );
    const grouplessDocSetName = `groupless-set-${stamp}`;
    const grouplessDocSetId = await managerClient2.createDocumentSet(
      grouplessDocSetName,
      [grouplessCcPairId],
      { isPublic: false, groups: [grouplessGroupId] }
    );
    await managerClient2.detachDocumentSetGroups(
      grouplessDocSetId,
      grouplessDocSetName,
      [grouplessCcPairId]
    );

    await page.context().clearCookies();
    await loginAs(page, "admin");
    await adminClient.setGroupCcPairs(grouplessGroupId, grouplessGroupName, []);

    try {
      await use({
        manager: scopedManager,
        managedCcPairId,
        grouplessCcPairId,
        foreignCcPairId,
        managedDocSetId,
        managedDocSetName,
        grouplessDocSetId,
        grouplessDocSetName,
        ownActionId,
        connectedActionId,
        orphanActionId,
      });
    } finally {
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanup = new OnyxApiClient(page.request);
      for (const id of [ownActionId, connectedActionId, orphanActionId]) {
        await softCleanup(() => cleanup.deleteCustomTool(id));
      }
      await softCleanup(() =>
        cleanup.setGroupCcPairs(foreignGroupId, foreignGroupName, [], {
          waitForSync: false,
        })
      );
      await softCleanup(() => cleanup.deleteUserGroup(foreignGroupId));
      await softCleanup(() => cleanup.deleteUserGroup(grouplessGroupId));
    }
  },
});

/** Log the browser in as the scoped manager and return a client bound to them. */
export async function actAsManager(
  page: Parameters<typeof apiLogin>[0],
  manager: ScopedManagerContext
): Promise<OnyxApiClient> {
  await page.context().clearCookies();
  await apiLogin(page, manager.email, manager.password);
  return new OnyxApiClient(page.request);
}

/** True when the permission registry is absent, i.e. a CE environment. */
export async function isCommunityEdition(
  registryResponse: APIResponse
): Promise<boolean> {
  return registryResponse.status() === 404;
}

export { expect };
