import { test, expect } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

test.use({ storageState: "admin_auth.json" });

test.describe("User Groups - No Vector DB @exclusive", () => {
  let client: OnyxApiClient;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    client = new OnyxApiClient(context.request);

    const vectorDbEnabled = await client.isVectorDbEnabled();
    test.skip(
      vectorDbEnabled,
      "Skipped: vector DB is enabled in this deployment"
    );
  });

  test("should show user group as synced immediately on creation", async ({
    page,
  }) => {
    const vectorDbEnabled = await new OnyxApiClient(
      page.request
    ).isVectorDbEnabled();
    test.skip(
      vectorDbEnabled,
      "Skipped: vector DB is enabled in this deployment"
    );

    const groupName = `E2E-NoVectorDB-Group-${Date.now()}`;
    let groupId: number | undefined;

    try {
      await page.goto("/admin/groups");
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Create New User Group" }).click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();

      await dialog.locator('input[name="name"]').fill(groupName);

      await expect(
        dialog.getByText("Connectors are not available in Onyx Lite")
      ).toBeVisible();

      await dialog.getByRole("button", { name: "Create!" }).click();

      await expect(dialog).not.toBeVisible({ timeout: 10000 });

      const groupRow = page.getByRole("row").filter({ hasText: groupName });
      await expect(groupRow).toBeVisible({ timeout: 10000 });
      await expect(groupRow.getByText("Up to date!")).toBeVisible();

      const groupLink = groupRow.getByRole("link", { name: groupName });
      const href = await groupLink.getAttribute("href");
      const match = href?.match(/\/admin\/groups\/(\d+)/);
      if (match) {
        groupId = parseInt(match[1] ?? "", 10);
      }

      await groupLink.click();
      await page.waitForLoadState("networkidle");

      await expect(page.getByText("Up to date")).toBeVisible({ timeout: 5000 });

      const addMembersButton = page.getByRole("button", {
        name: "Add Members",
      });
      await expect(addMembersButton).toBeEnabled();
    } finally {
      if (groupId !== undefined) {
        const apiClient = new OnyxApiClient(page.request);
        await apiClient.deleteUserGroup(groupId);
      }
    }
  });
});

test.describe("User Groups - Standard Deployment @exclusive", () => {
  let client: OnyxApiClient;
  let ccPairId: number | undefined;
  let groupId: number | undefined;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    client = new OnyxApiClient(context.request);

    const vectorDbEnabled = await client.isVectorDbEnabled();
    test.skip(
      !vectorDbEnabled,
      "Skipped: vector DB is disabled in this deployment"
    );
  });

  test.afterAll(async () => {
    if (groupId !== undefined) {
      await client.deleteUserGroup(groupId).catch(() => {});
    }
    if (ccPairId !== undefined) {
      await client.deleteCCPair(ccPairId).catch(() => {});
    }
  });

  test("should sync user group with connector", async ({ page }) => {
    const apiClient = new OnyxApiClient(page.request);
    const vectorDbEnabled = await apiClient.isVectorDbEnabled();
    test.skip(
      !vectorDbEnabled,
      "Skipped: vector DB is disabled in this deployment"
    );

    const groupName = `E2E-Sync-Group-${Date.now()}`;

    ccPairId = await apiClient.createFileConnector(
      `E2E-Group-Connector-${Date.now()}`,
      "private"
    );

    groupId = await apiClient.createUserGroup(groupName, [], [ccPairId]);

    await page.goto("/admin/groups");
    await page.waitForLoadState("networkidle");

    const groupRow = page.getByRole("row").filter({ hasText: groupName });
    await expect(groupRow).toBeVisible({ timeout: 10000 });

    await expect(groupRow.getByText("Up to date!")).toBeVisible({
      timeout: 60000,
    });

    const groupLink = groupRow.getByRole("link", { name: groupName });
    await groupLink.click();
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Up to date")).toBeVisible({ timeout: 10000 });
  });
});
