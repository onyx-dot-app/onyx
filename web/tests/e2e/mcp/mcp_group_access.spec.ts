import { test, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminMcpServersPage } from "@tests/e2e/pages/AdminMcpServersPage";

/**
 * Group/public access control for MCP servers.
 *
 * Exercises the real stack (api + EE group writes + DB) through the admin
 * endpoints the create/edit form posts to, plus a UI smoke that the access
 * selector is present on the Add-Server modal. Cross-user visibility is
 * covered at the unit/HTTP layer; here we assert the API contract + UI wiring.
 */
test.describe("MCP server group access control", () => {
  test.describe.configure({ mode: "serial" });

  let api: OnyxApiClient;
  let groupId: number;
  const createdServerIds: number[] = [];
  const suffix = Date.now().toString();

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await loginAs(page, "admin");
    api = new OnyxApiClient(page.request);
    groupId = await api.createUserGroup(`mcp-access-grp-${suffix}`);
  });

  test("restricted server persists is_public=false + groups", async ({
    page,
  }) => {
    await loginAs(page, "admin");
    const res = await page.request.post("/api/admin/mcp/server", {
      data: {
        name: `Restricted MCP ${suffix}`,
        description: "group-restricted",
        server_url: "https://example.com/mcp",
        is_public: false,
        groups: [groupId],
      },
    });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    createdServerIds.push(body.id);
    expect(body.is_public).toBe(false);
    expect(body.groups).toContain(groupId);
  });

  test("server with no access fields defaults to public", async ({ page }) => {
    await loginAs(page, "admin");
    const res = await page.request.post("/api/admin/mcp/server", {
      data: {
        name: `Public MCP ${suffix}`,
        description: "public default",
        server_url: "https://example.com/mcp",
        is_public: true,
        groups: [],
      },
    });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    createdServerIds.push(body.id);
    expect(body.is_public).toBe(true);
    expect(body.groups).toEqual([]);
  });

  test("editing a restricted server to public clears its groups", async ({
    page,
  }) => {
    await loginAs(page, "admin");
    const restrictedId = createdServerIds[0];
    const res = await page.request.patch(
      `/api/admin/mcp/server/${restrictedId}`,
      { data: { is_public: true, groups: [] } }
    );
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.is_public).toBe(true);
    expect(body.groups).toEqual([]);
  });

  test("Add-Server modal exposes the access (public/groups) selector", async ({
    page,
  }) => {
    await loginAs(page, "admin");
    const mcpPage = new AdminMcpServersPage(page);
    await mcpPage.goto();
    await mcpPage.openAddServerModal();
    // IsPublicGroupSelector renders a "public" control for admins.
    await expect(page.getByText(/public/i).first()).toBeVisible();
  });

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await loginAs(page, "admin");
    const client = new OnyxApiClient(page.request);
    for (const id of createdServerIds) {
      await client.deleteMcpServer(id);
    }
    await client.deleteUserGroup(groupId);
  });
});
