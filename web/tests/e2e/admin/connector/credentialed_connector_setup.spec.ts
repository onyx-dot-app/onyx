import { test, expect } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { ConnectorSetupPage } from "@tests/e2e/admin/connector/ConnectorSetupPage";

/**
 * The credential gate on the single-page connector setup: for a source that
 * needs a credential, the configuration stays disabled and Connect stays
 * disabled until one is selected; once selected and the required fields are
 * filled, Connect enables.
 *
 * Confluence is the source because it needs a credential and the credential
 * endpoint stores the JSON without contacting the source, so a placeholder
 * credential can be created and cleaned up through the API. The form is never
 * submitted: that would validate against a real Confluence instance.
 */
const SOURCE = "confluence";
const WIKI_BASE = "https://example.atlassian.net/wiki";

test.describe("Credentialed connector setup", () => {
  let credentialName: string;
  let credentialId: number | null = null;

  test.beforeEach(async ({ page }) => {
    credentialName = `Confluence Credential E2E ${Date.now()}`;
    const apiClient = new OnyxApiClient(page.request);
    credentialId = await apiClient.createCredential(SOURCE, credentialName, {
      confluence_username: "e2e@example.com",
      confluence_access_token: "placeholder",
    });
  });

  test.afterEach(async ({ page }) => {
    if (credentialId === null) return;
    const apiClient = new OnyxApiClient(page.request);
    try {
      await apiClient.deleteCredential(credentialId);
    } catch (error) {
      console.warn(
        `Failed to clean up credential "${credentialName}": ${error}`
      );
    }
    credentialId = null;
  });

  test("configuration and Connect wait for a credential", async ({ page }) => {
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

    // Selecting a credential unlocks the configuration. Connect still waits
    // for the required fields, since validation runs as soon as the form
    // changes.
    await expect(setupPage.connectorNameInput).toBeEnabled();
    await expect(setupPage.createConnectorButton).toBeDisabled();

    await setupPage.connectorNameInput.fill(`Confluence E2E ${Date.now()}`);
    await setupPage.textField("wiki_base").fill(WIKI_BASE);

    await expect(setupPage.createConnectorButton).toBeEnabled();
  });
});
