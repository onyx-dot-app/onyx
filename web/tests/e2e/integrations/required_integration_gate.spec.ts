import { test, type Browser } from "@playwright/test";
import { apiLogin } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { RequiredIntegrationGate } from "@tests/e2e/pages/RequiredIntegrationGate";
import type { IntegrationCreate } from "@/lib/integrations/types";

/**
 * An integration that an admin made Required for the company, with a per-user
 * API key. A member must connect it before they use the app. An admin can
 * continue without connecting. The gate blocks every user while the
 * integration exists, so the spec runs alone in the exclusive project.
 */
test.describe("Required integration gate @exclusive", () => {
  test.describe.configure({ mode: "serial" });

  const suffix = Date.now().toString();
  const integrationName = `PW Required ${suffix}`;
  const member = {
    email: `pw-required-member-${suffix}@example.com`,
    password: "TestPassword123!",
  };
  let integrationId: number | null = null;

  const integration: IntegrationCreate = {
    for_organization: true,
    name: integrationName,
    description: "Required integration gate e2e",
    auth_mode: "individual",
    auth_method: "api_key",
    credential_fields: [{ key: "api_key", label: "API Key", secret: true }],
    header_template: { Authorization: "Bearer {api_key}" },
    oauth_client: null,
    config: {
      shape: "openapi",
      openapi_spec: {
        openapi: "3.0.0",
        info: {
          title: integrationName,
          description: "Health",
          version: "1.0.0",
        },
        servers: [{ url: "https://example.com" }],
        paths: {
          "/health": {
            get: {
              operationId: "read_health",
              summary: "Read health",
              responses: { "200": { description: "OK" } },
            },
          },
        },
      },
    },
  };

  async function withAdmin<T>(
    browser: Browser,
    run: (client: OnyxApiClient) => Promise<T>
  ): Promise<T> {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      return await run(new OnyxApiClient(context.request));
    } finally {
      await context.close();
    }
  }

  test.beforeAll(async ({ browser }) => {
    await withAdmin(browser, async (client) => {
      await client.registerUser(member.email, member.password);
      integrationId = (await client.createIntegration(integration)).id;
      await client.setIntegrationInstallationPolicy(integrationId, "REQUIRED");
    });
  });

  test.afterAll(async ({ browser }) => {
    await withAdmin(browser, async (client) => {
      if (integrationId !== null) await client.deleteIntegration(integrationId);
    });
  });

  test("a member connects each Required integration before using the app", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, member.email, member.password);
    const gate = new RequiredIntegrationGate(page);

    await gate.gotoApp();
    await gate.expectVisible();
    await gate.expectRequired(integrationName);
    await gate.expectContinueDisabled();
    await gate.pressEscape();
    await gate.expectVisible();

    await gate.connectWithCredentials(integrationName, {
      "API Key": "pw-member-key",
    });
    await gate.expectConnected(integrationName);
    await gate.expectContinueEnabled();
    await gate.continue();
    await gate.expectHidden();

    // A connected member is not asked again.
    await page.reload();
    await gate.expectAppUsable();
  });

  test("an admin can continue without connecting", async ({ page }) => {
    // The page signs in as the admin of the exclusive project.
    const gate = new RequiredIntegrationGate(page);

    await gate.gotoApp();
    await gate.expectVisible();
    await gate.expectRequired(integrationName);
    await gate.expectAdminNote();
    await gate.continue();
    await gate.expectAppUsable();

    // The choice lasts only for the page session.
    await page.reload();
    await gate.expectVisible();
  });
});
