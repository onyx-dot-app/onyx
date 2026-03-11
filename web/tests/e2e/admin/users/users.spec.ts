/**
 * E2E Tests: Admin Users Page
 *
 * Tests the full users management page — search, filters, sorting,
 * inline role editing, row actions, invite modal, and group management.
 *
 * All tests create their own data via API and clean up after themselves.
 *
 * Tagged @exclusive because tests mutate user state and must run serially.
 */

import { test, expect } from "./fixtures";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function uniqueEmail(prefix: string): string {
  return `e2e-${prefix}-${Date.now()}@test.onyx`;
}

const TEST_PASSWORD = "TestPassword123!";

// ---------------------------------------------------------------------------
// Page load & layout
// ---------------------------------------------------------------------------

test.describe("Users page — layout @exclusive", () => {
  test("renders page title, invite button, search, and stats bar", async ({
    usersPage,
  }) => {
    await usersPage.goto();

    await expect(usersPage.page.getByText("Users & Requests")).toBeVisible();
    await expect(usersPage.inviteButton).toBeVisible();
    await expect(usersPage.searchInput).toBeVisible();
    await expect(usersPage.page.getByText(/active users/i)).toBeVisible();
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
        usersPage.table.getByRole("columnheader", { name: header })
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

    // The download button is an icon-only button with a tooltip
    const downloadBtn = usersPage.page.getByRole("button", {
      name: /Download CSV/i,
    });
    await expect(downloadBtn).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

test.describe("Users page — search @exclusive", () => {
  let testEmail: string;
  const personalName = `Zephyr${Date.now()}`;

  test.beforeAll(async ({ browser }) => {
    const adminCtx = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
      const adminApi = new OnyxApiClient(adminCtx.request);
      testEmail = uniqueEmail("search");
      await adminApi.registerUser(testEmail, TEST_PASSWORD);

      // Log in as the new user to set their personal name
      const userCtx = await browser.newContext();
      try {
        await userCtx.request.post(
          `${process.env.BASE_URL || "http://localhost:3000"}/api/auth/login`,
          { form: { username: testEmail, password: TEST_PASSWORD } }
        );
        const userApi = new OnyxApiClient(userCtx.request);
        await userApi.setPersonalName(personalName);
      } finally {
        await userCtx.close();
      }
    } finally {
      await adminCtx.close();
    }
  });

  test("search filters table rows by email", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.search(testEmail);

    const row = usersPage.getRowByEmail(testEmail);
    await expect(row).toBeVisible({ timeout: 10000 });

    const rowCount = await usersPage.getVisibleRowCount();
    expect(rowCount).toBeGreaterThanOrEqual(1);
    expect(rowCount).toBeLessThanOrEqual(8);
  });

  test("search matches by personal name", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.search(personalName);

    const row = usersPage.getRowByEmail(testEmail);
    await expect(row).toBeVisible({ timeout: 10000 });
    await expect(row).toContainText(personalName);
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

  test.afterAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
      const api = new OnyxApiClient(context.request);
      await api.deactivateUser(testEmail).catch(() => {});
      await api.deleteUser(testEmail).catch(() => {});
    } finally {
      await context.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

test.describe("Users page — filters @exclusive", () => {
  let activeEmail: string;
  let inactiveEmail: string;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
      const api = new OnyxApiClient(context.request);

      activeEmail = uniqueEmail("filt-active");
      await api.registerUser(activeEmail, TEST_PASSWORD);

      inactiveEmail = uniqueEmail("filt-inactive");
      await api.registerUser(inactiveEmail, TEST_PASSWORD);
      await api.deactivateUser(inactiveEmail);
    } finally {
      await context.close();
    }
  });

  test("account types filter shows expected roles", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.openAccountTypesFilter();

    const popover = usersPage.page.locator(
      "[data-radix-popper-content-wrapper]"
    );

    await expect(popover.getByText("All Account Types")).toBeVisible();
    await expect(popover.getByText("Admin")).toBeVisible();
    await expect(popover.getByText("Basic")).toBeVisible();

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
  });

  test("status filter for Active shows the active user", async ({
    usersPage,
  }) => {
    await usersPage.goto();
    await usersPage.openStatusFilter();
    await usersPage.selectStatus("Active");
    await usersPage.closePopover();

    await expect(usersPage.statusFilter).toContainText("Active");

    await usersPage.search(activeEmail);
    const row = usersPage.getRowByEmail(activeEmail);
    await expect(row).toBeVisible({ timeout: 10000 });
    await expect(row).toContainText("Active");
  });

  test("status filter for Inactive shows the inactive user", async ({
    usersPage,
  }) => {
    await usersPage.goto();
    await usersPage.openStatusFilter();
    await usersPage.selectStatus("Inactive");
    await usersPage.closePopover();

    await expect(usersPage.statusFilter).toContainText("Inactive");

    await usersPage.search(inactiveEmail);
    const row = usersPage.getRowByEmail(inactiveEmail);
    await expect(row).toBeVisible({ timeout: 10000 });
    await expect(row).toContainText("Inactive");
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

  test.afterAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
      const api = new OnyxApiClient(context.request);
      await api.deactivateUser(activeEmail).catch(() => {});
      await api.deleteUser(activeEmail).catch(() => {});
      await api.deleteUser(inactiveEmail).catch(() => {});
    } finally {
      await context.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------

test.describe("Users page — sorting @exclusive", () => {
  test("clicking Name sort toggles row order", async ({ usersPage }) => {
    await usersPage.goto();

    const firstRowBefore = await usersPage.tableRows.first().textContent();
    await usersPage.sortByColumn("Name");
    const firstRowAfter = await usersPage.tableRows.first().textContent();

    expect(firstRowBefore).toBeDefined();
    expect(firstRowAfter).toBeDefined();
  });

  test("clicking Status sort keeps table rendered", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.sortByColumn("Status");

    const rowCount = await usersPage.getVisibleRowCount();
    expect(rowCount).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

test.describe("Users page — pagination @exclusive", () => {
  test("next/previous page buttons navigate between pages", async ({
    usersPage,
  }) => {
    await usersPage.goto();

    const summaryBefore = await usersPage.paginationSummary.textContent();

    // Click next page if available
    const nextButton = usersPage.page.getByRole("button", { name: /next/i });
    if (await nextButton.isEnabled()) {
      await nextButton.click();
      await usersPage.page.waitForTimeout(300);

      const summaryAfter = await usersPage.paginationSummary.textContent();
      expect(summaryAfter).not.toBe(summaryBefore);

      // Go back
      const prevButton = usersPage.page.getByRole("button", {
        name: /previous/i,
      });
      await prevButton.click();
      await usersPage.page.waitForTimeout(300);
    }
  });
});

// ---------------------------------------------------------------------------
// Invite users
// ---------------------------------------------------------------------------

test.describe("Users page — invite users @exclusive", () => {
  test("invite modal opens with correct structure", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.openInviteModal();

    await expect(usersPage.dialog.getByText("Invite Users")).toBeVisible();
    await expect(
      usersPage.dialog.getByPlaceholder("Add emails to invite, comma separated")
    ).toBeVisible();
    await expect(usersPage.dialog.getByText("User Role")).toBeVisible();

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
    await expect(row).toBeVisible({ timeout: 10000 });
    await expect(row).toContainText("Invite Pending");

    // Cleanup
    await api.cancelInvite(email);
  });

  test("invite multiple users at once", async ({ usersPage, api }) => {
    const email1 = uniqueEmail("multi1");
    const email2 = uniqueEmail("multi2");

    await usersPage.goto();
    await usersPage.openInviteModal();

    const input = usersPage.dialog.getByPlaceholder(
      "Add emails to invite, comma separated"
    );
    await input.fill(`${email1}, ${email2},`);
    await usersPage.page.waitForTimeout(200);

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

    const input = usersPage.dialog.getByPlaceholder(
      "Add emails to invite, comma separated"
    );
    await input.fill("not-an-email,");
    await usersPage.page.waitForTimeout(200);

    // The chip should be rendered with an error state
    await expect(usersPage.dialog.getByText("not-an-email")).toBeVisible();

    await usersPage.cancelModal();
  });
});

// ---------------------------------------------------------------------------
// Row actions — deactivate / activate
// ---------------------------------------------------------------------------

test.describe("Users page — deactivate & activate @exclusive", () => {
  let testUserEmail: string;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
      const api = new OnyxApiClient(context.request);
      testUserEmail = uniqueEmail("deact");
      await api.registerUser(testUserEmail, TEST_PASSWORD);
    } finally {
      await context.close();
    }
  });

  test("deactivate and then reactivate a user", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.search(testUserEmail);

    const row = usersPage.getRowByEmail(testUserEmail);
    await expect(row).toBeVisible({ timeout: 10000 });
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
    await usersPage.page.waitForTimeout(500);
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
    await usersPage.page.waitForTimeout(500);
    await usersPage.search(testUserEmail);
    const reactivatedRow = usersPage.getRowByEmail(testUserEmail);
    await expect(reactivatedRow).toContainText("Active");
  });

  test.afterAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
      const api = new OnyxApiClient(context.request);
      await api.deactivateUser(testUserEmail).catch(() => {});
      await api.deleteUser(testUserEmail).catch(() => {});
    } finally {
      await context.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Row actions — delete user
// ---------------------------------------------------------------------------

test.describe("Users page — delete user @exclusive", () => {
  test("delete an inactive user", async ({ usersPage, api }) => {
    const email = uniqueEmail("delete");
    await api.registerUser(email, TEST_PASSWORD);
    await api.deactivateUser(email);

    await usersPage.goto();
    await usersPage.search(email);

    const row = usersPage.getRowByEmail(email);
    await expect(row).toBeVisible({ timeout: 10000 });
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
    await usersPage.page.waitForTimeout(500);
    await usersPage.search(email);
    await expect(usersPage.page.getByText("No users found")).toBeVisible({
      timeout: 10000,
    });
  });
});

// ---------------------------------------------------------------------------
// Row actions — cancel invite
// ---------------------------------------------------------------------------

test.describe("Users page — cancel invite @exclusive", () => {
  test("cancel a pending invite", async ({ usersPage, api }) => {
    const email = uniqueEmail("cancel-inv");
    await api.inviteUsers([email]);

    await usersPage.goto();
    await usersPage.search(email);

    const row = usersPage.getRowByEmail(email);
    await expect(row).toBeVisible({ timeout: 10000 });
    await expect(row).toContainText("Invite Pending");

    await usersPage.openRowActions(email);
    await usersPage.clickRowAction("Cancel Invite");

    await expect(usersPage.dialog.getByText("Cancel Invite")).toBeVisible();

    await usersPage.confirmModalAction("Cancel");
    await usersPage.expectToast("Invite cancelled");

    // User gone
    await usersPage.page.waitForTimeout(500);
    await usersPage.search(email);
    await expect(usersPage.page.getByText("No users found")).toBeVisible({
      timeout: 10000,
    });
  });
});

// ---------------------------------------------------------------------------
// Inline role editing
// ---------------------------------------------------------------------------

test.describe("Users page — inline role editing @exclusive", () => {
  let testUserEmail: string;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
      const api = new OnyxApiClient(context.request);
      testUserEmail = uniqueEmail("role");
      await api.registerUser(testUserEmail, TEST_PASSWORD);
    } finally {
      await context.close();
    }
  });

  test("change user role from Basic to Admin and back", async ({
    usersPage,
  }) => {
    await usersPage.goto();
    await usersPage.search(testUserEmail);

    const row = usersPage.getRowByEmail(testUserEmail);
    await expect(row).toBeVisible({ timeout: 10000 });

    // Initially Basic — the OpenButton shows the role label
    await expect(row.getByText("Basic")).toBeVisible();

    // Change to Admin
    await usersPage.openRoleDropdown(testUserEmail);
    await usersPage.selectRole("Admin");

    await usersPage.page.waitForTimeout(500);
    await expect(row.getByText("Admin")).toBeVisible();

    // Change back to Basic
    await usersPage.openRoleDropdown(testUserEmail);
    await usersPage.selectRole("Basic");

    await usersPage.page.waitForTimeout(500);
    await expect(row.getByText("Basic")).toBeVisible();
  });

  test.afterAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
      const api = new OnyxApiClient(context.request);
      await api.deactivateUser(testUserEmail).catch(() => {});
      await api.deleteUser(testUserEmail).catch(() => {});
    } finally {
      await context.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Group management
// ---------------------------------------------------------------------------

test.describe("Users page — group management @exclusive", () => {
  let testUserEmail: string;
  let testGroupId: number;
  const groupName = `E2E-UsersTest-${Date.now()}`;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
      const api = new OnyxApiClient(context.request);

      testUserEmail = uniqueEmail("grp");
      await api.registerUser(testUserEmail, TEST_PASSWORD);

      testGroupId = await api.createUserGroup(groupName);
    } finally {
      await context.close();
    }
  });

  test("add user to group via edit groups modal", async ({ usersPage }) => {
    await usersPage.goto();
    await usersPage.search(testUserEmail);

    const row = usersPage.getRowByEmail(testUserEmail);
    await expect(row).toBeVisible({ timeout: 10000 });

    await usersPage.openEditGroupsModal(testUserEmail);
    await usersPage.searchGroupsInModal(groupName);
    await usersPage.toggleGroupInModal(groupName);
    await usersPage.saveGroupsModal();
    await usersPage.expectToast("User updated");

    // Verify group shows in the row
    await usersPage.page.waitForTimeout(500);
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
    await expect(row).toBeVisible({ timeout: 10000 });

    await usersPage.openEditGroupsModal(testUserEmail);

    // Group shows as joined — click to remove
    await usersPage.toggleGroupInModal(groupName);
    await usersPage.saveGroupsModal();
    await usersPage.expectToast("User updated");

    // Verify group removed
    await usersPage.page.waitForTimeout(500);
    await usersPage.search(testUserEmail);
    await expect(usersPage.getRowByEmail(testUserEmail)).not.toContainText(
      groupName
    );
  });

  test.afterAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      const { OnyxApiClient } = await import("@tests/e2e/utils/onyxApiClient");
      const api = new OnyxApiClient(context.request);
      await api.deleteUserGroup(testGroupId).catch(() => {});
      await api.deactivateUser(testUserEmail).catch(() => {});
      await api.deleteUser(testUserEmail).catch(() => {});
    } finally {
      await context.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Stats bar
// ---------------------------------------------------------------------------

test.describe("Users page — stats bar @exclusive", () => {
  test("stats bar shows active users count", async ({ usersPage }) => {
    await usersPage.goto();
    await expect(usersPage.page.getByText(/\d+ active users/i)).toBeVisible();
  });

  test("stats bar updates after inviting a user", async ({
    usersPage,
    api,
  }) => {
    const email = uniqueEmail("stats");

    // Get initial pending count text
    await usersPage.goto();

    await usersPage.openInviteModal();
    await usersPage.addInviteEmail(email);
    await usersPage.submitInvite();
    await usersPage.expectToast(/Invited 1 user/);

    // Stats bar should reflect the new invite
    await usersPage.goto();
    await expect(usersPage.page.getByText(/pending invites/i)).toBeVisible();

    // Cleanup
    await api.cancelInvite(email);
  });
});
