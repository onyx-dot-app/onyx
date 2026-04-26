import { test, expect, type APIResponse } from "@playwright/test";
import { Permission } from "@/lib/types";
import { apiLogin, loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const TEST_PASSWORD = "PermissionSystem123!";

function uniqueEmail(prefix: string): string {
  return `e2e-permissions-${prefix}-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 8)}@example.com`;
}

async function softCleanup(fn: () => Promise<unknown>): Promise<void> {
  await fn().catch((e) => console.warn("cleanup:", e));
}

async function expectOk(response: APIResponse, message: string): Promise<void> {
  if (!response.ok()) {
    throw new Error(
      `${message}: ${response.status()} ${await response.text()}`
    );
  }
}

test("group permissions apply immediately when a user is added to the group", async ({
  page,
}) => {
  const email = uniqueEmail("llm");
  const groupName = `e2e-permissions-llm-${Date.now()}`;
  let groupId: number | undefined;

  await page.context().clearCookies();
  await loginAs(page, "admin");
  const adminClient = new OnyxApiClient(page.request);

  const registryResponse = await page.request.get(
    "/api/manage/admin/permissions/registry"
  );
  test.skip(
    registryResponse.status() === 404,
    "Group permission registry is unavailable in this environment"
  );
  await expectOk(registryResponse, "Failed to fetch permission registry");

  try {
    const user = await adminClient.registerUser(email, TEST_PASSWORD);
    groupId = await adminClient.createUserGroup(groupName);
    await adminClient.setUserGroupPermissions(groupId, [
      Permission.MANAGE_LLMS,
    ]);

    // This is intentionally not followed by waitForGroupSync. Auth permission
    // recomputation is expected to complete before add-users returns.
    await adminClient.addUsersToGroup(groupId, [user.id]);

    await page.context().clearCookies();
    await apiLogin(page, email, TEST_PASSWORD);

    const userClient = new OnyxApiClient(page.request);
    const permissions = await userClient.getCurrentUserPermissions();
    expect(permissions).toEqual(
      expect.arrayContaining([
        Permission.BASIC_ACCESS,
        Permission.MANAGE_LLMS,
        Permission.READ_USERS,
        Permission.READ_USER_GROUPS,
        Permission.READ_AGENTS,
      ])
    );
    expect(permissions).not.toContain(Permission.FULL_ADMIN_PANEL_ACCESS);
    expect(permissions).not.toContain(Permission.MANAGE_USER_GROUPS);

    const usersResponse = await page.request.get(
      "/api/manage/users?include_api_keys=false"
    );
    await expectOk(
      usersResponse,
      "manage:llms should imply read:users for LLM sharing UI"
    );

    await page.goto("/admin/configuration/llm");
    await expect(page.getByLabel("admin-page-title")).toContainText(
      "Language Models"
    );
    await expect(
      page.getByRole("link", { name: "Language Models" })
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Groups" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);

    await page.goto("/admin/users");
    await expect(page).toHaveURL(/\/admin\/configuration\/llm/);
  } finally {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const cleanupClient = new OnyxApiClient(page.request);

    if (groupId !== undefined) {
      await softCleanup(() => cleanupClient.deleteUserGroup(groupId!));
    }
    await softCleanup(() => cleanupClient.deactivateUser(email));
    await softCleanup(() => cleanupClient.deleteUser(email));
  }
});
