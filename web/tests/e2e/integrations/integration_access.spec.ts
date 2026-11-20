import { test, expect, type Browser } from "@playwright/test";
import { apiLogin, loginAs } from "@tests/e2e/utils/auth";
import { ensureOnboardingComplete } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";
import { CustomizePage } from "@tests/e2e/pages/CustomizePage";
import { CustomizeIntegrationPage } from "@tests/e2e/pages/CustomizeIntegrationPage";
import type {
  AuthMode,
  InstallationPolicy,
  IntegrationCreate,
} from "@/lib/integrations/types";

/**
 * An integration owns its access. A member row shows one state (On, Turn on,
 * Sign in, No access); the member turns an integration on and off; the owner
 * shares a private one; an admin sets the company install setting.
 */
test.describe("Integration access", () => {
  test.describe.configure({ mode: "serial" });

  const suffix = Date.now().toString();
  const onName = `PW On ${suffix}`;
  const turnOnName = `PW Turn On ${suffix}`;
  const signInName = `PW Sign In ${suffix}`;
  const privateName = `PW Private ${suffix}`;
  const member = {
    email: `pw-integration-access-${suffix}@example.com`,
    password: "TestPassword123!",
  };
  const ids: Record<string, number> = {};

  function server(
    name: string,
    forOrganization: boolean,
    authMode: AuthMode
  ): IntegrationCreate {
    return {
      for_organization: forOrganization,
      name,
      description: "Integration access e2e",
      auth_mode: authMode,
      auth_method: authMode === "none" ? null : "api_key",
      credential_fields:
        authMode === "none"
          ? null
          : [{ key: "api_key", label: "API Key", secret: true }],
      header_template:
        authMode === "none" ? null : { Authorization: "Bearer {api_key}" },
      oauth_client: null,
      config: {
        shape: "openapi",
        openapi_spec: {
          openapi: "3.0.0",
          info: { title: name, description: "Health", version: "1.0.0" },
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
  }

  async function withClient<T>(
    browser: Browser,
    storageState: string | null,
    run: (client: OnyxApiClient) => Promise<T>
  ): Promise<T> {
    const context = await browser.newContext(
      storageState ? { storageState } : {}
    );
    try {
      return await run(new OnyxApiClient(context.request));
    } finally {
      await context.close();
    }
  }

  test.beforeAll(async ({ browser }) => {
    await withClient(browser, "admin_auth.json", async (admin) => {
      const policies: [string, AuthMode, InstallationPolicy][] = [
        [onName, "none", "DEFAULT"],
        [turnOnName, "none", "AVAILABLE"],
        [signInName, "individual", "DEFAULT"],
      ];
      for (const [name, authMode, policy] of policies) {
        const created = await admin.createIntegration(
          server(name, true, authMode)
        );
        ids[name] = created.id;
        await admin.setIntegrationInstallationPolicy(created.id, policy);
      }
      await admin.registerUser(member.email, member.password);
    });
    // A second admin owns a private integration, so the first admin
    // manages it with no access of their own.
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAs(page, "admin2");
    const owner = new OnyxApiClient(page.request);
    ids[privateName] = (
      await owner.createIntegration(server(privateName, false, "none"))
    ).id;
    await context.close();
  });

  test.afterAll(async ({ browser }) => {
    await withClient(browser, "admin_auth.json", async (admin) => {
      for (const id of Object.values(ids)) await admin.deleteIntegration(id);
    });
  });

  test("a member row shows On, Turn on and Sign in, and a manager sees No access", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, member.email, member.password);
    await page.goto("/app");
    await ensureOnboardingComplete(page);
    const customize = new CustomizePage(page);
    await customize.goto("Integrations");
    await customize.search(suffix);
    await customize.expectIntegrationState(onName, "on");
    await customize.expectIntegrationState(turnOnName, "turn_on");
    await customize.expectIntegrationState(signInName, "sign_in");
    await customize.expectIntegrationAbsent(privateName);

    await page.context().clearCookies();
    await loginAs(page, "admin");
    const admin = new AdminIntegrationsPage(page);
    await admin.goto();
    await admin.expectNoAccess(privateName);
  });

  test("a member turns an integration on and off", async ({ page }) => {
    await page.context().clearCookies();
    await apiLogin(page, member.email, member.password);
    const customize = new CustomizePage(page);
    await customize.goto("Integrations");
    await customize.search(suffix);
    await customize.setIntegrationEnabled(turnOnName, true);
    await customize.expectIntegrationState(turnOnName, "on");

    const detail = new CustomizeIntegrationPage(page);
    await detail.goto(ids[turnOnName]!);
    await detail.setEnabled(turnOnName, false);

    await customize.goto("Integrations");
    await customize.search(suffix);
    await customize.expectIntegrationState(turnOnName, "turn_on");
  });

  test("the owner shares a private integration and the member then sees it", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin2");
    const detail = new CustomizeIntegrationPage(page);
    await detail.goto(ids[privateName]!);
    await detail.shareWith(privateName, member.email);

    await page.context().clearCookies();
    await apiLogin(page, member.email, member.password);
    const customize = new CustomizePage(page);
    await customize.goto("Integrations");
    await customize.search(suffix);
    await customize.expectIntegrationState(privateName, "turn_on");
  });

  test("an admin makes an integration Required and the member cannot turn it off", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const admin = new AdminIntegrationsPage(page);
    await admin.goto();
    await admin.setInstallSetting(turnOnName, "Required");

    await page.context().clearCookies();
    await apiLogin(page, member.email, member.password);
    const customize = new CustomizePage(page);
    await customize.goto("Integrations");
    await customize.search(suffix);
    await customize.expectIntegrationState(turnOnName, "on");
    await expect(customize.integrationSwitch(turnOnName)).toHaveAttribute(
      "aria-disabled",
      "true"
    );
  });
});
