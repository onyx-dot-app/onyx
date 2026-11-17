import { test, expect } from "@tests/e2e/fixtures/eeFeatures";
import { apiLogin } from "@tests/e2e/utils/auth";
import { ensureOnboardingComplete } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { MemberPluginsPage } from "@tests/e2e/pages/MemberPluginsPage";
import type { IntegrationCreate } from "@/lib/integrations/types";

/**
 * Access to an MCP server comes from the plugin that holds it: a plugin in
 * the Organization library reaches each member, and a plugin in "My uploads"
 * reaches only its owner until the owner shares it.
 */
test.describe("MCP server access through plugins", () => {
  test.describe.configure({ mode: "serial" });

  const suffix = Date.now().toString();
  const organizationName = `PW Org MCP ${suffix}`;
  const personalName = `PW Personal MCP ${suffix}`;
  const createdIds: number[] = [];
  let member: { email: string; password: string } | null = null;

  function server(name: string, forOrganization: boolean): IntegrationCreate {
    return {
      for_organization: forOrganization,
      name,
      description: "access test",
      auth_mode: "none",
      auth_method: null,
      credential_fields: null,
      header_template: null,
      oauth_client: null,
      config: {
        shape: "mcp_server",
        server_url: "https://example.com/mcp",
        transport: "STREAMABLE_HTTP",
      },
    };
  }

  test.beforeAll(async ({ browser }) => {
    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    for (const [name, forOrganization] of [
      [organizationName, true],
      [personalName, false],
    ] as const) {
      createdIds.push(
        (await adminClient.createIntegration(server(name, forOrganization))).id
      );
    }
    member = {
      email: `pw-access-${suffix}@example.com`,
      password: "TestPassword123!",
    };
    await adminClient.registerUser(member.email, member.password);
    await adminContext.close();
  });

  test.afterAll(async ({ browser }) => {
    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    for (const id of createdIds) await adminClient.deleteIntegration(id);
    await adminContext.close();
  });

  test("a member sees the Organization library server and not a personal one", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, member!.email, member!.password);
    await page.goto("/app");
    await ensureOnboardingComplete(page);

    const response = await page.request.get("/api/integrations");
    expect(response.ok()).toBeTruthy();
    const names = ((await response.json()) as { name: string }[]).map(
      (integration) => integration.name
    );
    expect(names).toContain(organizationName);
    expect(names).not.toContain(personalName);

    const plugins = new MemberPluginsPage(page);
    await plugins.goto();
    await plugins.search(suffix);
    await plugins.expectPluginVisible(organizationName);
    await plugins.expectPluginAbsent(personalName);
  });

  test("a member without manage:actions cannot add an integration", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, member!.email, member!.password);
    const response = await page.request.post("/api/admin/integrations", {
      data: server(`PW Denied MCP ${suffix}`, false),
    });
    expect(response.status()).toBe(403);
  });
});
