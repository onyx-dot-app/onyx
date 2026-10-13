import { test, expect } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { ConnectorSetupPage } from "@tests/e2e/admin/connector/ConnectorSetupPage";

/**
 * The credential gate on the single-page connector setup: for a source that
 * needs a credential, the configuration and Connect stay disabled until a
 * credential is selected and the credential-bound fields (for Confluence, the
 * site URL) form a valid combination with it, and the connector checks pass.
 * Once the required fields are filled, Connect enables.
 *
 * Confluence is the source because it needs a credential and the credential
 * endpoint stores the JSON without contacting the source, so a placeholder
 * credential can be created and cleaned up through the API. The form is never
 * submitted: that would validate against a real Confluence instance. The
 * connector checks are mocked for the same reason.
 */
const SOURCE = "confluence";
const WIKI_BASE = "https://example.atlassian.net/wiki";
const OTHER_WIKI_BASE = "https://other-example.atlassian.net/wiki";

test.describe("Credentialed connector setup", () => {
  let credentialName: string;
  let credentialId: number;
  // Every credential a test creates, deleted after the test.
  let credentialIds: number[] = [];

  test.beforeEach(async ({ page }) => {
    credentialName = `Confluence Credential E2E ${Date.now()}`;
    const apiClient = new OnyxApiClient(page.request);
    credentialId = await apiClient.createCredential(SOURCE, credentialName, {
      confluence_username: "e2e@example.com",
      confluence_access_token: "placeholder",
    });
    credentialIds = [credentialId];
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
    await setupPage.mockChecks();
    await setupPage.goto();

    // Every section is on the page at once, but without a credential the
    // configuration is disabled and so is Connect.
    await expect(setupPage.credentialRow(credentialId)).toBeVisible({
      timeout: 10_000,
    });
    await expect(setupPage.connectorNameInput).toBeDisabled();
    await expect(setupPage.createConnectorButton).toBeDisabled();
    await expect(setupPage.startChecksButton).toBeDisabled();

    await setupPage.selectCredential(credentialId);

    // A credential alone does not unlock the configuration: the site URL is a
    // credential-bound field and is still empty.
    await expect(setupPage.connectorNameInput).toBeDisabled();

    // The bound field sits above the credential and is editable already. Once
    // it is filled and the binding check passes, the checks can start. The
    // configuration unlocks once they pass. Connect still waits for the
    // required fields.
    const siteUrl = setupPage.textField("wiki_base");
    await expect(siteUrl).toBeEnabled();
    await siteUrl.fill(WIKI_BASE);
    await siteUrl.blur();
    await expect(setupPage.startChecksButton).toBeEnabled({ timeout: 10_000 });
    await expect(setupPage.connectorNameInput).toBeDisabled();
    await setupPage.runChecks();
    await expect(setupPage.createConnectorButton).toBeDisabled();

    await setupPage.connectorNameInput.fill(`Confluence E2E ${Date.now()}`);

    await expect(setupPage.createConnectorButton).toBeEnabled();
  });

  test("an OAuth credential fills in its authorized site and locks it", async ({
    page,
  }) => {
    // An OAuth-style credential names the one site it was authorized for.
    const oauthCredentialName = `Confluence OAuth Credential E2E ${Date.now()}`;
    const apiClient = new OnyxApiClient(page.request);
    const oauthCredentialId = await apiClient.createCredential(
      SOURCE,
      oauthCredentialName,
      {
        confluence_access_token: "placeholder",
        confluence_refresh_token: "placeholder",
        wiki_base: WIKI_BASE,
      }
    );
    credentialIds.push(oauthCredentialId);

    const setupPage = new ConnectorSetupPage(page, SOURCE);
    await setupPage.mockChecks();
    await setupPage.goto();
    await expect(setupPage.credentialRow(oauthCredentialId)).toBeVisible({
      timeout: 10_000,
    });

    // A site the account was not authorized for makes it unusable.
    const siteUrl = setupPage.textField("wiki_base");
    await siteUrl.fill(OTHER_WIKI_BASE);
    await siteUrl.blur();
    await expect(setupPage.credentialRow(oauthCredentialId)).toContainText(
      "Unsupported site domain"
    );

    // With the site cleared, picking the account fills in its site.
    await siteUrl.fill("");
    await siteUrl.blur();
    await setupPage.selectCredential(oauthCredentialId);

    await expect(siteUrl).toHaveValue(WIKI_BASE);
    await expect(siteUrl).toBeDisabled();
    await setupPage.runChecks();
  });
});
