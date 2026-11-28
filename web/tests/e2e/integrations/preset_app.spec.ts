import { expect, test } from "@playwright/test";
import { apiLogin, loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";
import { AdminIntegrationDetailPage } from "@tests/e2e/pages/AdminIntegrationDetailPage";
import { CustomizeIntegrationPage } from "@tests/e2e/pages/CustomizeIntegrationPage";

const PRESET = "GitHub";
const CLIENT_ID = "pw-github-client";

/**
 * An admin adds a catalog app for the organization with its OAuth client. A
 * member connects their own account: Onyx opens the provider's sign-in with
 * that client. The provider is stubbed, so the flow stops at its sign-in.
 */
test.describe("Catalog app", () => {
  let createdId: number | null = null;
  const member = {
    email: `pw-preset-member-${Date.now()}@example.com`,
    password: "TestPassword123!",
  };

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      await new OnyxApiClient(context.request).registerUser(
        member.email,
        member.password
      );
    } finally {
      await context.close();
    }
  });

  test.afterAll(async ({ browser }) => {
    if (createdId === null) return;
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      await new OnyxApiClient(context.request).deleteIntegration(createdId);
    } finally {
      await context.close();
    }
  });

  test("an admin adds it for the organization and a member starts sign-in", async ({
    page,
    browser,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const integrations = new AdminIntegrationsPage(page);
    await integrations.goto();
    await integrations.pickFromCatalog(PRESET);
    await integrations.fillPresetCredentials({
      "Client ID": CLIENT_ID,
      "Client Secret": "pw-github-secret",
    });
    await integrations.chooseOwner("For the organization");
    createdId = await integrations.submit();
    await new AdminIntegrationDetailPage(page).expectLoaded(PRESET);

    const memberContext = await browser.newContext();
    try {
      await memberContext.route("https://github.com/**", (route) =>
        route.fulfill({ contentType: "text/html", body: "GitHub sign-in" })
      );
      const memberPage = await memberContext.newPage();
      await apiLogin(memberPage, member.email, member.password);
      const detail = new CustomizeIntegrationPage(memberPage);
      await detail.openApp();
      await detail.goto(createdId);
      await detail.expectStatus("Not connected");
      const signIn = await detail.startOAuthConnect(PRESET);
      await signIn.waitForURL(
        /^https:\/\/github\.com\/login\/oauth\/authorize\?/
      );
      const authorize = new URL(signIn.url());
      expect(authorize.searchParams.get("client_id")).toBe(CLIENT_ID);
      expect(authorize.searchParams.get("redirect_uri")).toBeTruthy();
      await signIn.close();
      await detail.expectStatus("Not connected");
    } finally {
      await memberContext.close();
    }
  });
});
