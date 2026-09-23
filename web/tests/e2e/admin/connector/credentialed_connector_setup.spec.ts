import { test, expect } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { ConnectorSetupPage } from "@tests/e2e/admin/connector/ConnectorSetupPage";

/**
 * The credential gate on the single-page connector setup: for a source that
 * needs a credential, Connect stays disabled until one is selected, and the
 * configuration renders on the same page rather than behind a step.
 *
 * Confluence is the source because it needs a credential and the credential
 * endpoint stores the JSON without contacting the source, so a placeholder
 * credential can be created and cleaned up through the API. The form is never
 * submitted: that would validate against a real Confluence instance.
 */
const SOURCE = "confluence";

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

  test("Connect stays disabled until a credential is selected", async ({
    page,
  }) => {
    const setupPage = new ConnectorSetupPage(page, SOURCE);
    await setupPage.goto();

    // Every section is on the page at once: the credential list and the
    // configuration fields render together, with no step in between.
    await expect(setupPage.credentialRow(credentialName)).toBeVisible({
      timeout: 10_000,
    });
    await expect(setupPage.connectorNameInput).toBeVisible();
    await expect(setupPage.createConnectorButton).toBeDisabled();

    await setupPage.selectCredential(credentialName);

    await expect(setupPage.createConnectorButton).toBeEnabled();
  });
});
