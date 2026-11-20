import { test, expect } from "@tests/e2e/fixtures/eeFeatures";
import { apiLogin } from "@tests/e2e/utils/auth";
import { ensureOnboardingComplete } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { CustomizePage } from "@tests/e2e/pages/CustomizePage";
import type { IntegrationCreate } from "@/lib/integrations/types";

/**
 * An MCP server owns its access: a server for the organization reaches each
 * member, and a personal server reaches only its owner until the owner
 * shares it.
 */
test.describe("MCP server access", () => {
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
      auth_mode: "individual",
      auth_method: "api_key",
      credential_fields: [{ key: "api_key", label: "API Key", secret: true }],
      header_template: { Authorization: "Bearer {api_key}" },
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

  test("a member sees the organization server and not a personal one", async ({
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

    const customize = new CustomizePage(page);
    await customize.goto("Integrations");
    await customize.search(suffix);
    await customize.expectIntegrationVisible(organizationName);
    await customize.expectIntegrationAbsent(personalName);
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
