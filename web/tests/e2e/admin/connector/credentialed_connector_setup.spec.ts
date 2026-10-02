import { test, expect } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { ConnectorSetupPage } from "@tests/e2e/admin/connector/ConnectorSetupPage";

/**
 * The credential gate on the single-page connector setup: for a source that
 * needs a credential, the configuration and Connect stay disabled until a
 * credential is selected and the credential-bound fields (for Confluence, the
 * site URL) form a valid combination with it. Once the required fields are
 * filled, Connect enables.
 *
 * Confluence is the source because it needs a credential and the credential
 * endpoint stores the JSON without contacting the source, so a placeholder
 * credential can be created and cleaned up through the API. The form is never
 * submitted: that would validate against a real Confluence instance.
 */
const SOURCE = "confluence";
const WIKI_BASE = "https://example.atlassian.net/wiki";
const OTHER_WIKI_BASE = "https://other-example.atlassian.net/wiki";
// The end of the backend message for a site the account was not authorized
// for (`ConfluenceCredentialBinding`).
const REJECTION_TEXT =
  "is not the Confluence site this account was authorized for";

test.describe("Credentialed connector setup", () => {
  let credentialName: string;
  // Every credential a test creates, deleted after the test.
  let credentialIds: number[] = [];

  test.beforeEach(async ({ page }) => {
    credentialName = `Confluence Credential E2E ${Date.now()}`;
    const apiClient = new OnyxApiClient(page.request);
    credentialIds = [
      await apiClient.createCredential(SOURCE, credentialName, {
        confluence_username: "e2e@example.com",
        confluence_access_token: "placeholder",
      }),
    ];
  });

  test.afterEach(async ({ page }) => {
    const apiClient = new OnyxApiClient(page.request);
    for (const credentialId of credentialIds) {
      try {
        await apiClient.deleteCredential(credentialId);
      } catch (error) {
        console.warn(`Failed to clean up credential ${credentialId}: ${error}`);
      }
    }
    credentialIds = [];
  });

  test("configuration unlocks once the credential and site URL pass the binding check", async ({
    page,
  }) => {
    const setupPage = new ConnectorSetupPage(page, SOURCE);
    await setupPage.goto();

    // Every section is on the page at once, but without a credential the
    // configuration is disabled and so is Connect.
    await expect(setupPage.credentialRow(credentialName)).toBeVisible({
      timeout: 10_000,
    });
    await expect(setupPage.connectorNameInput).toBeDisabled();
    await expect(setupPage.createConnectorButton).toBeDisabled();

    await setupPage.selectCredential(credentialName);

    // A credential alone does not unlock the configuration: the site URL is a
    // credential-bound field and is still empty.
    await expect(setupPage.connectorNameInput).toBeDisabled();

    // The bound field sits above the credential and is editable already. Once
    // it is filled and the binding check passes, the configuration unlocks.
    // Connect still waits for the required fields.
    const siteUrl = setupPage.textField("wiki_base");
    await expect(siteUrl).toBeEnabled();
    await siteUrl.fill(WIKI_BASE);
    await siteUrl.blur();
    await expect(setupPage.connectorNameInput).toBeEnabled({ timeout: 10_000 });
    await expect(setupPage.createConnectorButton).toBeDisabled();

    await setupPage.connectorNameInput.fill(`Confluence E2E ${Date.now()}`);

    await expect(setupPage.createConnectorButton).toBeEnabled();
  });

  test("a site URL the credential is not authorized for keeps the configuration locked", async ({
    page,
  }) => {
    // An OAuth-style credential names the one site it was authorized for.
    const oauthCredentialName = `Confluence OAuth Credential E2E ${Date.now()}`;
    const apiClient = new OnyxApiClient(page.request);
    credentialIds.push(
      await apiClient.createCredential(SOURCE, oauthCredentialName, {
        confluence_access_token: "placeholder",
        confluence_refresh_token: "placeholder",
        wiki_base: WIKI_BASE,
      })
    );

    const setupPage = new ConnectorSetupPage(page, SOURCE);
    await setupPage.goto();
    await expect(setupPage.credentialRow(oauthCredentialName)).toBeVisible({
      timeout: 10_000,
    });
    await setupPage.selectCredential(oauthCredentialName);

    const siteUrl = setupPage.textField("wiki_base");
    await siteUrl.fill(OTHER_WIKI_BASE);
    await siteUrl.blur();

    // The backend rejects the pair, and the configuration says why.
    await expect(
      setupPage.configurationSection.getByText(REJECTION_TEXT)
    ).toBeVisible({ timeout: 10_000 });
    await expect(setupPage.connectorNameInput).toBeDisabled();
    await expect(setupPage.createConnectorButton).toBeDisabled();

    // The authorized site unlocks it.
    await siteUrl.fill(WIKI_BASE);
    await siteUrl.blur();
    await expect(setupPage.connectorNameInput).toBeEnabled({ timeout: 10_000 });
    await expect(
      setupPage.configurationSection.getByText(REJECTION_TEXT)
    ).toHaveCount(0);
  });
});
