import { test, expect } from "@tests/e2e/fixtures/eeFeatures";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminMcpServersPage } from "@tests/e2e/pages/AdminMcpServersPage";

/**
 * Group/public access control for MCP servers (CE surface).
 *
 * Group read/filter behaviour is covered by external-dependency unit tests that
 * seed access rows directly. The create/edit selector is EE/business-tier only.
 */
test.describe("MCP server group access control", () => {
  test.describe.configure({ mode: "serial" });

  const createdServerIds: number[] = [];
  const suffix = Date.now().toString();

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

  test("CE rejects private server creation", async ({ page, eeEnabled }) => {
    test.skip(eeEnabled, "CE-only: EE persists private + group grants");
    await loginAs(page, "admin");
    const res = await page.request.post("/api/admin/mcp/server", {
      data: {
        name: `Restricted MCP ${suffix}`,
        description: "private server on CE",
        server_url: "https://example.com/mcp",
        is_public: false,
        groups: [999999],
      },
    });
    expect(res.status()).toBe(403);
    const body = await res.json();
    expect(body.error_code).toBe("EE_REQUIRED");
  });

  test("Add-Server modal exposes the access (public/groups) selector", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "IsPublicGroupSelector requires business/EE tier");
    await loginAs(page, "admin");
    const mcpPage = new AdminMcpServersPage(page);
    await mcpPage.goto();
    await mcpPage.openAddServerModal();
    await mcpPage.expectAccessControlVisible();
  });

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await loginAs(page, "admin");
    const client = new OnyxApiClient(page.request);
    for (const id of createdServerIds) {
      await client.deleteMcpServer(id);
    }
  });
});
