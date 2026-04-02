/**
 * E2E Tests: Admin Groups Page
 *
 * Tests the full groups management page — list, create, edit, delete.
 *
 * Uses the GroupsAdminPage POM for all interactions. Groups are created via
 * OnyxApiClient for setup and cleaned up in afterAll/afterEach.
 */

import { test, expect } from "./fixtures";
import type { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import type { Browser } from "@playwright/test";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function uniqueGroupName(prefix: string): string {
  return `e2e-${prefix}-${Date.now()}`;
}

/** Best-effort cleanup — logs failures instead of silently swallowing them. */
async function softCleanup(fn: () => Promise<unknown>): Promise<void> {
  await fn().catch((e) => console.warn("cleanup:", e));
}

/**
 * Creates an authenticated API context for beforeAll/afterAll hooks.
 */
async function withApiContext(
  browser: Browser,
  fn: (api: OnyxApiClient) => Promise<void>
): Promise<void> {
  const context = await browser.newContext({
    storageState: "admin_auth.json",
  });
  try {
    const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
    const api = new OnyxApiClient(context.request);
    await fn(api);
  } finally {
    await context.close();
  }
}

// ---------------------------------------------------------------------------
// List page
// ---------------------------------------------------------------------------

test.describe("Groups page — layout", () => {
  let adminGroupId: number;
  let basicGroupId: number;
  let layoutGroupId: number;
  const layoutGroupName = uniqueGroupName("layout");

  test.beforeAll(async ({ browser }) => {
    await withApiContext(browser, async (api) => {
      const groups = await api.getUserGroups();
      const adminGroup = groups.find((g) => g.name === "Admin" && g.is_default);
      const basicGroup = groups.find((g) => g.name === "Basic" && g.is_default);
      if (!adminGroup || !basicGroup) {
        throw new Error("Default Admin/Basic groups not found");
      }
      adminGroupId = adminGroup.id;
      basicGroupId = basicGroup.id;

      // Create a custom group so the list is non-empty (default groups are
      // excluded from the API response by default).
      layoutGroupId = await api.createUserGroup(layoutGroupName);
      await api.waitForGroupSync(layoutGroupId);
    });
  });

  test.afterAll(async ({ browser }) => {
    await withApiContext(browser, async (api) => {
      await softCleanup(() => api.deleteUserGroup(layoutGroupId));
    });
  });

  test("renders page title, search, and new group button", async ({
    groupsPage,
  }) => {
    await groupsPage.goto();

    await expect(groupsPage.pageHeading).toBeVisible();
    await expect(groupsPage.listSearchInput).toBeVisible();
    await expect(groupsPage.newGroupButton).toBeVisible();
  });

  test.skip("shows built-in groups (Admin, Basic)", async ({ groupsPage }) => {
    // TODO: Enable once default groups are shown via include_default=true
    await groupsPage.goto();

    await groupsPage.expectGroupVisible("Admin");
    await groupsPage.expectGroupVisible("Basic");
  });

  test("search filters groups by name", async ({ groupsPage, api }) => {
    const name = uniqueGroupName("search");
    const groupId = await api.createUserGroup(name);
    await api.waitForGroupSync(groupId);

    try {
      await groupsPage.goto();
      await groupsPage.expectGroupVisible(name);

      await groupsPage.searchGroups("zzz-nonexistent-zzz");
      await groupsPage.expectGroupNotVisible(name);

      await groupsPage.searchGroups(name);
      await groupsPage.expectGroupVisible(name);
    } finally {
      await softCleanup(() => api.deleteUserGroup(groupId));
    }
  });
});

// ---------------------------------------------------------------------------
// Create flow
// ---------------------------------------------------------------------------

test.describe("Groups page — create", () => {
  test("navigates to create page via New Group button", async ({
    groupsPage,
  }) => {
    await groupsPage.goto();
    await groupsPage.clickNewGroup();

    await expect(groupsPage.page).toHaveURL(/\/admin\/groups\/create/);
    await expect(groupsPage.groupNameInput).toBeVisible();
  });

  test("creates a group and redirects to list", async ({ groupsPage, api }) => {
    const name = uniqueGroupName("create");
    let groupId: number | undefined;

    try {
      await groupsPage.gotoCreate();
      await groupsPage.setGroupName(name);
      await groupsPage.submitCreate();

      await groupsPage.expectToast(`Group "${name}" created`);
      await groupsPage.expectOnListPage();

      // Find the group ID for cleanup via the authenticated page context
      const res = await groupsPage.page.request.get(
        "/api/manage/admin/user-group"
      );
      const groups = await res.json();
      const group = groups.find(
        (g: { name: string; id: number }) => g.name === name
      );
      groupId = group?.id;
    } finally {
      if (groupId !== undefined) {
        await softCleanup(() => api.deleteUserGroup(groupId!));
      }
    }
  });

  test("cancel returns to list without creating", async ({ groupsPage }) => {
    await groupsPage.gotoCreate();
    await groupsPage.setGroupName("should-not-be-created");
    await groupsPage.cancelButton.click();

    await groupsPage.expectOnListPage();
  });
});

// ---------------------------------------------------------------------------
// Edit flow
// ---------------------------------------------------------------------------

test.describe("Groups page — edit @exclusive", () => {
  let groupId: number;
  const groupName = uniqueGroupName("edit");

  test.beforeAll(async ({ browser }) => {
    await withApiContext(browser, async (api) => {
      groupId = await api.createUserGroup(groupName);
      await api.waitForGroupSync(groupId);
    });
  });

  test.afterAll(async ({ browser }) => {
    await withApiContext(browser, async (api) => {
      await softCleanup(() => api.deleteUserGroup(groupId));
    });
  });

  test("navigates to edit page from list", async ({ groupsPage }) => {
    await groupsPage.goto();
    await groupsPage.openGroup(groupName);

    await groupsPage.expectOnEditPage(groupId);
    await expect(groupsPage.saveButton).toBeVisible();
  });

  test("edit page shows group name and save/cancel buttons", async ({
    groupsPage,
  }) => {
    await groupsPage.gotoEdit(groupId);

    await expect(groupsPage.groupNameInput).toHaveValue(groupName);
    await expect(groupsPage.saveButton).toBeVisible();
    await expect(groupsPage.cancelButton).toBeVisible();
  });

  test("can toggle add-members mode", async ({ groupsPage }) => {
    await groupsPage.gotoEdit(groupId);

    await expect(groupsPage.addMembersButton).toBeVisible();
    await groupsPage.startAddingMembers();
    await expect(groupsPage.doneAddingButton).toBeVisible();
    await groupsPage.finishAddingMembers();
    await expect(groupsPage.addMembersButton).toBeVisible();
  });

  test("cancel returns to list without saving", async ({ groupsPage }) => {
    await groupsPage.gotoEdit(groupId);
    await groupsPage.cancelButton.click();

    await groupsPage.expectOnListPage();
  });
});

// ---------------------------------------------------------------------------
// Delete flow
// ---------------------------------------------------------------------------

test.describe("Groups page — delete", () => {
  test("delete group via edit page", async ({ groupsPage, api }) => {
    const name = uniqueGroupName("delete");
    const groupId = await api.createUserGroup(name);
    await api.waitForGroupSync(groupId);

    await groupsPage.gotoEdit(groupId);
    await groupsPage.clickDeleteGroup();

    // Modal should show the group name
    await expect(groupsPage.deleteModal).toBeVisible();
    await expect(groupsPage.deleteModal.getByText(name)).toBeVisible();

    await groupsPage.confirmDelete();
    await groupsPage.expectToast(`Group "${name}" deleted`);
    await groupsPage.expectOnListPage();
  });
});

// ---------------------------------------------------------------------------
// Sync status (No Vector DB)
// ---------------------------------------------------------------------------

test.describe("Groups page — sync @lite", () => {
  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
      const client = new OnyxApiClient(context.request);
      const vectorDbEnabled = await client.isVectorDbEnabled();
      test.skip(
        vectorDbEnabled,
        "Skipped: vector DB is enabled in this deployment"
      );
    } finally {
      await context.close();
    }
  });

  test("newly created group syncs immediately", async ({ groupsPage, api }) => {
    const name = uniqueGroupName("sync");
    let groupId: number | undefined;

    try {
      // Create via API and verify sync completes
      groupId = await api.createUserGroup(name);
      await api.waitForGroupSync(groupId);

      // Navigate to edit page and verify it loads without error
      await groupsPage.gotoEdit(groupId);
      await expect(groupsPage.groupNameInput).toHaveValue(name);
    } finally {
      if (groupId !== undefined) {
        await softCleanup(() => api.deleteUserGroup(groupId!));
      }
    }
  });
});
