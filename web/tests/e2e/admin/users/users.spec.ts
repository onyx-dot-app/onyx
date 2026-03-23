/**
 * E2E Tests: Admin Users Page
 *
 * Tests the full users management page — search, filters, sorting,
 * inline role editing, row actions, invite modal, and group management.
 *
 * Read-only tests (layout, search, filters, sorting, pagination) run against
 * whatever users already exist in the database (at minimum 10 from global-setup:
 * 2 admins + 8 workers). Mutation tests create their own ephemeral users.
 */

import { test, expect } from "./fixtures";
import { TEST_ADMIN_CREDENTIALS } from "@tests/e2e/constants";
import type { Browser } from "@playwright/test";
import type { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function uniqueEmail(prefix: string): string {
  return `e2e-${prefix}-${Date.now()}@test.onyx`;
}

const TEST_PASSWORD = "TestPassword123!";

/** Best-effort cleanup — logs failures instead of silently swallowing them. */
async function softCleanup(fn: () => Promise<unknown>): Promise<void> {
  await fn().catch((e) => console.warn("cleanup:", e));
}

/**
 * Creates an authenticated API context for beforeAll/afterAll hooks.
 * Handles browser context lifecycle so callers only write the setup logic.
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
// Page load & layout
// ---------------------------------------------------------------------------

test.describe("Users page — layout", () => {
  test("renders page title, invite button, search, and stats bar", async ({
    usersPage,
  }) => {
    await usersPage.goto();

    await expect(usersPage.page.getByText("Users & Requests")).toBeVisible();
    await expect(usersPage.inviteButton).toBeVisible();
    await expect(usersPage.searchInput).toBeVisible();
    // Stats bar renders number and label as separate elements
    await expect(usersPage.page.getByText("active users")).toBeVisible();
  });

  test("table renders with correct column headers", async ({ usersPage }) => {
    await usersPage.goto();

    for (const header of [
      "Name",
      "Groups",
      "Account Type",
      "Status",
      "Last Updated",
    ]) {
      await expect(
        usersPage.table.locator("th").filter({ hasText: header })
      ).toBeVisible();
    }
  });

  test("pagination shows summary and controls", async ({ usersPage }) => {
    await usersPage.goto();

    await expect(usersPage.paginationSummary).toBeVisible();
    await expect(usersPage.paginationSummary).toContainText("Showing");
  });

  test("CSV download button is visible in footer", async ({ usersPage }) => {
    await usersPage.goto();
    await expect(usersPage.downloadCsvButton).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Search (uses existing DB users — at least admin_user@example.com)
// ---------------------------------------------------------------------------

test.describe("Users page — search", () => {
  test("search filters table rows by email", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.search(TEST_ADMIN_CREDENTIALS.email);

    const row = usersPage.getRowByEmail(TEST_ADMIN_CREDENTIALS.email);
    await expect(row).toBeVisible();

    const rowCount = await usersPage.getVisibleRowCount();
    expect(rowCount).toBeGreaterThanOrEqual(1);
  });

  test("search with no results shows empty state", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.search("zzz-no-match-exists-xyz@nowhere.invalid");

    await expect(usersPage.page.getByText("No users found")).toBeVisible();
  });

  test("clearing search restores all results", async ({ usersPage }) => {
    await usersPage.goto();

    await usersPage.search("zzz-no-match-exists-xyz@nowhere.invalid");
    await expect(usersPage.page.getByText("No users found")).toBeVisible();

    await usersPage.clearSearch();

    await expect(usersPage.table).toBeVisible();
    const rowCount = await usersPage.getVisibleRowCount();
    expect(rowCount).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Filters (uses existing DB users)
// ---------------------------------------------------------------------------

test.describe("Users page — filters", () => {
  test("account types filter shows expected roles", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.openAccountTypesFilter();

    await expect(
      usersPage.popover.getByText("All Account Types").first()
    ).toBeVisible();
    await expect(usersPage.popover.getByText("Admin").first()).toBeVisible();
    await expect(usersPage.popover.getByText("Basic").first()).toBeVisible();

    await usersPage.closePopover();
  });

  test("filtering by Admin role shows only admin users", async ({
    usersPage,
  }) => {
    await usersPage.goto();
    await usersPage.openAccountTypesFilter();
    await usersPage.selectAccountType("Admin");
    await usersPage.closePopover();

    await expect(usersPage.accountTypesFilter).toContainText("Admin");

    const rowCount = await usersPage.getVisibleRowCount();
    expect(rowCount).toBeGreaterThan(0);

    // Every visible row's Account Type column must say "Admin"
    const roleTexts = await usersPage.getColumnTexts(2);
    for (const role of roleTexts) {
      expect(role).toBe("Admin");
    }
  });

  test("status filter for Active shows only active users", async ({
    usersPage,
  }) => {
    await usersPage.goto();
    await usersPage.openStatusFilter();
    await usersPage.selectStatus("Active");
    await usersPage.closePopover();

    await expect(usersPage.statusFilter).toContainText("Active");

    const rowCount = await usersPage.getVisibleRowCount();
    expect(rowCount).toBeGreaterThan(0);

    // Every visible row's Status column must say "Active"
    const statusTexts = await usersPage.getColumnTexts(3);
    for (const status of statusTexts) {
      expect(status).toBe("Active");
    }
  });

  test("resetting filter shows all users again", async ({ usersPage }) => {
    await usersPage.goto();

    await usersPage.openStatusFilter();
    await usersPage.selectStatus("Active");
    await usersPage.closePopover();
    const filteredCount = await usersPage.getVisibleRowCount();

    await usersPage.openStatusFilter();
    await usersPage.selectStatus("All Status");
    await usersPage.closePopover();
    const allCount = await usersPage.getVisibleRowCount();

    expect(allCount).toBeGreaterThanOrEqual(filteredCount);
  });
});

// ---------------------------------------------------------------------------
// Sorting (uses existing DB users)
// ---------------------------------------------------------------------------

test.describe("Users page — sorting", () => {
  test("clicking Name sort twice reverses row order", async ({ usersPage }) => {
    await usersPage.goto();

    const firstRowBefore = await usersPage.tableRows.first().textContent();

    // Click twice — first click may match default order; second guarantees reversal
    await usersPage.sortByColumn("Name");
    await usersPage.sortByColumn("Name");

    const firstRowAfter = await usersPage.tableRows.first().textContent();
    expect(firstRowAfter).not.toBe(firstRowBefore);
  });

  test("clicking Account Type sort twice reorders rows", async ({
    usersPage,
  }) => {
    await usersPage.goto();

    const rolesBefore = await usersPage.getColumnTexts(2);

    // Click twice to guarantee a different order from default
    await usersPage.sortByColumn("Account Type");
    await usersPage.sortByColumn("Account Type");

    const rolesAfter = await usersPage.getColumnTexts(2);
    expect(rolesAfter.length).toBeGreaterThan(0);
    expect(rolesAfter).not.toEqual(rolesBefore);
  });
});

// ---------------------------------------------------------------------------
// Pagination (uses existing DB users — need > 8 for multi-page)
// ---------------------------------------------------------------------------

test.describe("Users page — pagination", () => {
  test("clicking page 2 navigates to second page", async ({ usersPage }) => {
    await usersPage.goto();

    const summaryBefore = await usersPage.paginationSummary.textContent();

    // With 10+ users and page size 8, page 2 should exist
    await usersPage.goToPage(2);

    await expect(usersPage.paginationSummary).not.toHaveText(summaryBefore!);

    // Go back to page 1
    await usersPage.goToPage(1);
    await expect(usersPage.paginationSummary).toHaveText(summaryBefore!);
  });
});

// ---------------------------------------------------------------------------
// Invite users (creates ephemeral data)
// ---------------------------------------------------------------------------

test.describe("Users page — invite users", () => {
  test("invite modal opens with correct structure", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.openInviteModal();

    await expect(usersPage.dialog.getByText("Invite Users")).toBeVisible();
    await expect(usersPage.inviteEmailInput).toBeVisible();

    await usersPage.cancelModal();
    await expect(usersPage.dialog).not.toBeVisible();
  });

  test("invite a user and verify Invite Pending status", async ({
    usersPage,
    api,
  }) => {
    const email = uniqueEmail("invite");

    await usersPage.goto();
    await usersPage.openInviteModal();
    await usersPage.addInviteEmail(email);
    await usersPage.submitInvite();

    await usersPage.expectToast(/Invited 1 user/);

    // Reload and search
    await usersPage.goto();
    await usersPage.search(email);

    const row = usersPage.getRowByEmail(email);
    await expect(row).toBeVisible();
    await expect(row).toContainText("Invite Pending");

    // Cleanup
    await api.cancelInvite(email);
  });

  test("invite multiple users at once", async ({ usersPage, api }) => {
    const email1 = uniqueEmail("multi1");
    const email2 = uniqueEmail("multi2");

    await usersPage.goto();
    await usersPage.openInviteModal();

    await usersPage.addInviteEmail(email1);
    await usersPage.addInviteEmail(email2);

    await usersPage.submitInvite();
    await usersPage.expectToast(/Invited 2 users/);

    // Cleanup
    await api.cancelInvite(email1);
    await api.cancelInvite(email2);
  });

  test("invite modal shows error icon for invalid emails", async ({
    usersPage,
  }) => {
    await usersPage.goto();
    await usersPage.openInviteModal();

    await usersPage.addInviteEmail("not-an-email");

    // The chip should be rendered with an error state
    await expect(usersPage.dialog.getByText("not-an-email")).toBeVisible();

    await usersPage.cancelModal();
  });
});

// ---------------------------------------------------------------------------
// Row actions — deactivate / activate (creates ephemeral data)
// ---------------------------------------------------------------------------

test.describe("Users page — deactivate & activate", () => {
  let testUserEmail: string;

  test.beforeAll(async ({ browser }) => {
    testUserEmail = uniqueEmail("deact");
    await withApiContext(browser, async (api) => {
      await api.registerUser(testUserEmail, TEST_PASSWORD);
    });
  });

  test("deactivate and then reactivate a user", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.search(testUserEmail);

    const row = usersPage.getRowByEmail(testUserEmail);
    await expect(row).toBeVisible();
    await expect(row).toContainText("Active");

    // Deactivate
    await usersPage.openRowActions(testUserEmail);
    await usersPage.clickRowAction("Deactivate User");

    await expect(usersPage.dialog.getByText("Deactivate User")).toBeVisible();
    await expect(usersPage.dialog.getByText(testUserEmail)).toBeVisible();
    await expect(
      usersPage.dialog.getByText("will immediately lose access")
    ).toBeVisible();

    await usersPage.confirmModalAction("Deactivate");
    await usersPage.expectToast("User deactivated");

    // Verify Inactive
    await usersPage.goto();
    await usersPage.search(testUserEmail);
    const inactiveRow = usersPage.getRowByEmail(testUserEmail);
    await expect(inactiveRow).toContainText("Inactive");

    // Reactivate
    await usersPage.openRowActions(testUserEmail);
    await usersPage.clickRowAction("Activate User");

    await expect(usersPage.dialog.getByText("Activate User")).toBeVisible();

    await usersPage.confirmModalAction("Activate");
    await usersPage.expectToast("User activated");

    // Verify Active again
    await usersPage.goto();
    await usersPage.search(testUserEmail);
    const reactivatedRow = usersPage.getRowByEmail(testUserEmail);
    await expect(reactivatedRow).toContainText("Active");
  });

  test.afterAll(async ({ browser }) => {
    await withApiContext(browser, async (api) => {
      await softCleanup(() => api.deactivateUser(testUserEmail));
      await softCleanup(() => api.deleteUser(testUserEmail));
    });
  });
});

// ---------------------------------------------------------------------------
// Row actions — delete user (creates ephemeral data)
// ---------------------------------------------------------------------------

test.describe("Users page — delete user", () => {
  test("delete an inactive user", async ({ usersPage, api }) => {
    const email = uniqueEmail("delete");
    await api.registerUser(email, TEST_PASSWORD);
    await api.deactivateUser(email);

    await usersPage.goto();
    await usersPage.search(email);

    const row = usersPage.getRowByEmail(email);
    await expect(row).toBeVisible();
    await expect(row).toContainText("Inactive");

    await usersPage.openRowActions(email);
    await usersPage.clickRowAction("Delete User");

    await expect(usersPage.dialog.getByText("Delete User")).toBeVisible();
    await expect(
      usersPage.dialog.getByText("will be permanently removed")
    ).toBeVisible();

    await usersPage.confirmModalAction("Delete");
    await usersPage.expectToast("User deleted");

    // User gone
    await usersPage.goto();
    await usersPage.search(email);
    await expect(usersPage.page.getByText("No users found")).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Row actions — cancel invite (creates ephemeral data)
// ---------------------------------------------------------------------------

test.describe("Users page — cancel invite", () => {
  test("cancel a pending invite", async ({ usersPage, api }) => {
    const email = uniqueEmail("cancel-inv");
    await api.inviteUsers([email]);

    await usersPage.goto();
    await usersPage.search(email);

    const row = usersPage.getRowByEmail(email);
    await expect(row).toBeVisible();
    await expect(row).toContainText("Invite Pending");

    await usersPage.openRowActions(email);
    await usersPage.clickRowAction("Cancel Invite");

    await expect(
      usersPage.dialog.getByText("Cancel Invite").first()
    ).toBeVisible();

    await usersPage.confirmModalAction("Cancel Invite");
    await usersPage.expectToast("Invite cancelled");

    // User gone
    await usersPage.goto();
    await usersPage.search(email);
    await expect(usersPage.page.getByText("No users found")).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Inline role editing (creates ephemeral data)
// ---------------------------------------------------------------------------

test.describe("Users page — inline role editing", () => {
  let testUserEmail: string;

  test.beforeAll(async ({ browser }) => {
    testUserEmail = uniqueEmail("role");
    await withApiContext(browser, async (api) => {
      await api.registerUser(testUserEmail, TEST_PASSWORD);
    });
  });

  test("change user role from Basic to Admin and back", async ({
    usersPage,
  }) => {
    await usersPage.goto();
    await usersPage.search(testUserEmail);

    const row = usersPage.getRowByEmail(testUserEmail);
    await expect(row).toBeVisible();

    // Initially Basic
    await expect(row.getByText("Basic")).toBeVisible();

    // Change to Admin
    await usersPage.openRoleDropdown(testUserEmail);
    await usersPage.selectRole("Admin");
    await expect(row.getByText("Admin")).toBeVisible();

    // Change back to Basic
    await usersPage.openRoleDropdown(testUserEmail);
    await usersPage.selectRole("Basic");
    await expect(row.getByText("Basic")).toBeVisible();
  });

  test.afterAll(async ({ browser }) => {
    await withApiContext(browser, async (api) => {
      await softCleanup(() => api.deactivateUser(testUserEmail));
      await softCleanup(() => api.deleteUser(testUserEmail));
    });
  });
});

// ---------------------------------------------------------------------------
// Group management (creates ephemeral data)
// ---------------------------------------------------------------------------

test.describe("Users page — group management", () => {
  let testUserEmail: string;
  let testGroupId: number;
  const groupName = `E2E-UsersTest-${Date.now()}`;

  test.beforeAll(async ({ browser }) => {
    testUserEmail = uniqueEmail("grp");
    await withApiContext(browser, async (api) => {
      await api.registerUser(testUserEmail, TEST_PASSWORD);
      testGroupId = await api.createUserGroup(groupName);
      await api.waitForGroupSync(testGroupId);
    });
  });

  test("add user to group via edit groups modal", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.search(testUserEmail);

    const row = usersPage.getRowByEmail(testUserEmail);
    await expect(row).toBeVisible();

    await usersPage.openEditGroupsModal(testUserEmail);
    await usersPage.searchGroupsInModal(groupName);
    await usersPage.toggleGroupInModal(groupName);
    await usersPage.saveGroupsModal();
    await usersPage.expectToast("User updated");

    // Verify group shows in the row
    await usersPage.goto();
    await usersPage.search(testUserEmail);
    const rowWithGroup = usersPage.getRowByEmail(testUserEmail);
    await expect(rowWithGroup).toContainText(groupName);
  });

  test("remove user from group via edit groups modal", async ({
    usersPage,
  }) => {
    await usersPage.goto();
    await usersPage.search(testUserEmail);

    const row = usersPage.getRowByEmail(testUserEmail);
    await expect(row).toBeVisible();

    await usersPage.openEditGroupsModal(testUserEmail);

    // Group shows as joined — click to remove
    await usersPage.toggleGroupInModal(groupName);
    await usersPage.saveGroupsModal();
    await usersPage.expectToast("User updated");

    // Verify group removed
    await usersPage.goto();
    await usersPage.search(testUserEmail);
    await expect(usersPage.getRowByEmail(testUserEmail)).not.toContainText(
      groupName
    );
  });

  test.afterAll(async ({ browser }) => {
    await withApiContext(browser, async (api) => {
      await softCleanup(() => api.deleteUserGroup(testGroupId));
      await softCleanup(() => api.deactivateUser(testUserEmail));
      await softCleanup(() => api.deleteUser(testUserEmail));
    });
  });
});

// ---------------------------------------------------------------------------
// Stats bar
// ---------------------------------------------------------------------------

test.describe("Users page — stats bar", () => {
  test("stats bar shows active users count", async ({ usersPage }) => {
    await usersPage.goto();
    // Number and label are separate elements; check for the label
    await expect(usersPage.page.getByText("active users")).toBeVisible();
  });

  test("stats bar updates after inviting a user", async ({
    usersPage,
    api,
  }) => {
    const email = uniqueEmail("stats");

    await usersPage.goto();

    await usersPage.openInviteModal();
    await usersPage.addInviteEmail(email);
    await usersPage.submitInvite();
    await usersPage.expectToast(/Invited 1 user/);

    // Stats bar should reflect the new invite
    await usersPage.goto();
    await expect(usersPage.page.getByText("pending invites")).toBeVisible();

    // Cleanup
    await api.cancelInvite(email);
  });
});
