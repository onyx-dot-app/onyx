import { test, type Browser } from "@playwright/test";
import { apiLogin } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { RequiredIntegrationGate } from "@tests/e2e/pages/RequiredIntegrationGate";
import type { IntegrationCreate } from "@/lib/integrations/types";

// A company-wide Required integration blocks every user, so this spec runs
// alone in the exclusive project.
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

    await gate.gotoNewTabPage();
    await gate.expectVisible();

    await gate.gotoApp();
    await gate.expectVisible();
    await gate.expectRequired(integrationName);
    await gate.expectProgress(0, 1);
    await gate.expectContinueDisabled();
    await gate.pressEscape();
    await gate.expectVisible();

    await gate.connectWithCredentials(integrationName, {
      "API Key": "pw-member-key",
    });
    await gate.expectConnected(integrationName);
    await gate.expectProgress(1, 1);
    await gate.expectContinueEnabled();
    await gate.continue();
    await gate.expectHidden();

    await page.reload();
    await gate.expectAppUsable();
  });

  test("an admin continues without connecting once per browser session", async ({
    page,
  }) => {
    const gate = new RequiredIntegrationGate(page);

    await gate.gotoApp();
    await gate.expectVisible();
    await gate.expectRequired(integrationName);
    await gate.expectAdminDescription();
    await gate.continue();
    await gate.expectAppUsable();

    await page.reload();
    await gate.expectAppUsable();
  });
});
