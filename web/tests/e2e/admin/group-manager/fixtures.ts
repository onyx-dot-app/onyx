/*
 * Scoped-manager e2e fixtures. Seeding is worker-scoped — a user, three groups and
 * several sync waits — so it runs once per worker rather than once per test. That is
 * only safe while every consuming test stays read-only: assert on affordances, never
 * exercise them. Admin and manager each get their own browser context, so seeding
 * never re-points the identity a test sets on its own `page`.
 */
import {
  test as base,
  expect,
  type APIResponse,
  type Browser,
  type Page,
} from "@playwright/test";
import { loginAs, apiLogin } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const TEST_PASSWORD = "ScopedManager123!";

// browser.newContext() ignores the project's `use` block, so apiLogin's relative URLs need this
const BASE_URL = process.env.BASE_URL || "http://localhost:3000";

function uniqueId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function softCleanup(fn: () => Promise<unknown>): Promise<void> {
  await fn().catch((e) => console.warn("cleanup:", e));
}

async function openAs(
  browser: Browser,
  login: (page: Page) => Promise<void>
): Promise<{ page: Page; close: () => Promise<void> }> {
  const context = await browser.newContext({ baseURL: BASE_URL });
  const page = await context.newPage();
  await login(page);
  return { page, close: () => context.close() };
}

export interface ScopedManagerContext {
  userId: string;
  groupId: number;
  groupName: string;
  email: string;
  password: string;
}

export const test = base.extend<
  {},
  {
    adminPage: Page;
    adminClient: OnyxApiClient;
    scopedManager: ScopedManagerContext;
  }
>({
  adminPage: [
    async ({ browser }, use) => {
      const admin = await openAs(browser, (page) => loginAs(page, "admin"));
      await use(admin.page);
      await admin.close();
    },
    { scope: "worker" },
  ],

  adminClient: [
    async ({ adminPage }, use) => {
      await use(new OnyxApiClient(adminPage.request));
    },
    { scope: "worker" },
  ],

  // authority is the is_manager edge alone — no global permission is granted
  scopedManager: [
    async ({ adminClient }, use) => {
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

        await use({
          userId,
          groupId,
          groupName,
          email,
          password: TEST_PASSWORD,
        });
      } finally {
        if (groupId !== undefined) {
          // a group with connectors still attached refuses deletion
          await softCleanup(() =>
            adminClient.setGroupCcPairs(groupId!, groupName, [], {
              waitForSync: false,
            })
          );
          await softCleanup(() => adminClient.deleteUserGroup(groupId!));
        }
        await softCleanup(() => adminClient.deactivateUser(email));
        await softCleanup(() => adminClient.deleteUser(email));
      }
    },
    { scope: "worker" },
  ],
});

/** In-scope resources paired with out-of-scope twins, so an assertion proves the boundary. */
export interface ScopedWorld {
  manager: ScopedManagerContext;
  /** in the managed group — editable, not deletable */
  managedCcPairId: number;
  /** manager-created, in no group — editable and deletable */
  grouplessCcPairId: number;
  /** in an unmanaged group — invisible */
  foreignCcPairId: number;
  managedDocSetId: number;
  managedDocSetName: string;
  grouplessDocSetId: number;
  grouplessDocSetName: string;
  ownActionId: number;
  /** admin's, visible only via an agent in the managed group */
  connectedActionId: number;
  /** admin's, on no agent — invisible */
  orphanActionId: number;
}

export const worldTest = test.extend<{}, { world: ScopedWorld }>({
  world: [
    async ({ browser, adminClient, scopedManager }, use) => {
      // workers seed at startup, so a bare timestamp collides
      const stamp = uniqueId("world");

      const foreignGroupName = `e2e-scoped-foreign-${stamp}`;
      const foreignGroupId =
        await adminClient.createUserGroup(foreignGroupName);
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
      const bridgeAgentId = await adminClient.createAgent(
        `bridge-agent-${stamp}`,
        "",
        {
          isPublic: false,
          groups: [scopedManager.groupId],
          toolIds: [connectedActionId],
        }
      );

      // a groupless pair can't be created directly, so it starts in a group and loses it
      const grouplessGroupName = `e2e-scoped-tmp-${stamp}`;
      const grouplessGroupId = await adminClient.createUserGroup(
        grouplessGroupName,
        [scopedManager.userId]
      );
      await adminClient.waitForGroupSync(grouplessGroupId);
      await adminClient.setGroupManager(grouplessGroupId, scopedManager.userId);

      const manager = await openAs(browser, (page) =>
        apiLogin(page, scopedManager.email, scopedManager.password)
      );
      const managerClient = new OnyxApiClient(manager.page.request);

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

      const grouplessCcPairId = await managerClient.createFileConnector(
        `groupless-conn-${stamp}`,
        "private",
        [grouplessGroupId]
      );
      const grouplessDocSetName = `groupless-set-${stamp}`;
      const grouplessDocSetId = await managerClient.createDocumentSet(
        grouplessDocSetName,
        [grouplessCcPairId],
        { isPublic: false, groups: [grouplessGroupId] }
      );
      await managerClient.detachDocumentSetGroups(
        grouplessDocSetId,
        grouplessDocSetName,
        [grouplessCcPairId]
      );

      await adminClient.setGroupCcPairs(
        grouplessGroupId,
        grouplessGroupName,
        []
      );

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
        // referrer before referent: agent holds an action, doc set its cc_pair, group both
        await softCleanup(() => adminClient.deleteAgent(bridgeAgentId));
        for (const id of [ownActionId, connectedActionId, orphanActionId]) {
          await softCleanup(() => adminClient.deleteCustomTool(id));
        }
        for (const id of [managedDocSetId, grouplessDocSetId]) {
          await softCleanup(() => adminClient.deleteDocumentSet(id));
        }
        for (const id of [
          managedCcPairId,
          grouplessCcPairId,
          foreignCcPairId,
        ]) {
          await softCleanup(() => adminClient.deleteCCPair(id));
        }
        await softCleanup(() =>
          adminClient.setGroupCcPairs(foreignGroupId, foreignGroupName, [], {
            waitForSync: false,
          })
        );
        await softCleanup(() => adminClient.deleteUserGroup(foreignGroupId));
        await softCleanup(() => adminClient.deleteUserGroup(grouplessGroupId));
        await manager.close();
      }
    },
    { scope: "worker" },
  ],
});

export async function actAsManager(
  page: Parameters<typeof apiLogin>[0],
  manager: ScopedManagerContext
): Promise<OnyxApiClient> {
  await page.context().clearCookies();
  await apiLogin(page, manager.email, manager.password);
  return new OnyxApiClient(page.request);
}

/** CE ships no permission registry, so a 404 identifies it. */
export async function isCommunityEdition(
  registryResponse: APIResponse
): Promise<boolean> {
  return registryResponse.status() === 404;
}

export { expect };
