import { expect, test } from "@playwright/test";
import {
  GoogleDriveConnectorSetupPage,
  SERVICE_ACCOUNT_KEY,
} from "@tests/e2e/pages/GoogleDriveConnectorSetupPage";
import { MOCK_DRAFT_CREDENTIAL_ID } from "@tests/e2e/utils/connectorChecks";

test.describe("Google Drive connector setup", () => {
  test("submits a service account typed into the form", async ({ page }) => {
    const setup = new GoogleDriveConnectorSetupPage(page);
    await setup.mockRoutes();
    await setup.goto();
    await setup.openAccountForm();

    // The email starts empty: nothing fills it in.
    await setup.expectPrimaryAdminEmpty();

    await setup.fillServiceAccount("admin@example.com");
    await setup.runChecks();
    await setup.submitConnector("Service Account Drive");
    await setup.expectCreated();

    expect(setup.credentialJson).toEqual({
      authentication_method: "uploaded",
      google_primary_admin: "admin@example.com",
      google_service_account_key: SERVICE_ACCOUNT_KEY,
    });
    expect(setup.connectorConfigs[0]).toMatchObject({
      credential_kind: "service_account",
    });
    // Create names the draft the check run saved.
    expect(setup.createCredentials).toHaveLength(1);
    expect(setup.createCredentials[0]?.credential_id).toBe(
      MOCK_DRAFT_CREDENTIAL_ID
    );
    const sentValues = setup.createCredentials[0]?.credential_json;
    if (sentValues !== undefined) {
      expect(sentValues).toEqual(setup.credentialJson);
    }
  });

  test("signs in with OAuth from its own tab", async ({ page }) => {
    const setup = new GoogleDriveConnectorSetupPage(page);
    await setup.mockRoutes();
    await setup.goto();
    await setup.openAccountForm();
    await setup.openOAuthTab();

    // The sign-in saves the account itself, so the tab has no Create step.
    await setup.expectOAuthSetup();
  });
});
