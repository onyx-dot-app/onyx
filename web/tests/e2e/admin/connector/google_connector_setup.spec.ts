import { expect, test } from "@playwright/test";
import {
  GoogleConnectorSetupPage,
  SERVICE_ACCOUNT_KEY,
  type GoogleSource,
} from "@tests/e2e/pages/GoogleConnectorSetupPage";
import { MOCK_DRAFT_CREDENTIAL_ID } from "@tests/e2e/utils/connectorChecks";

// Gmail and Google Drive share one account form.
const SOURCES: { source: GoogleSource; name: string }[] = [
  { source: "google_drive", name: "Google Drive" },
  { source: "gmail", name: "Gmail" },
];

for (const { source, name } of SOURCES) {
  test.describe(`${name} connector setup`, () => {
    test("submits a service account typed into the form", async ({ page }) => {
      const setup = new GoogleConnectorSetupPage(page, source);
      await setup.mockRoutes();
      await setup.goto();
      await setup.openAccountForm();

      // The email starts empty: nothing fills it in.
      await setup.expectPrimaryAdminEmpty();

      await setup.fillServiceAccount("admin@example.com");
      await setup.runChecks();
      await setup.submitConnector(`Service Account ${name}`);
      await setup.expectCreated();

      expect(setup.credentialJson).toEqual({
        authentication_method: "uploaded",
        google_primary_admin: "admin@example.com",
        google_service_account_key: SERVICE_ACCOUNT_KEY,
      });
      // Drive reads the account's kind into its config; Gmail has no config.
      if (source === "google_drive") {
        expect(setup.connectorConfigs[0]).toMatchObject({
          credential_kind: "service_account",
        });
      }
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
      const setup = new GoogleConnectorSetupPage(page, source);
      await setup.mockRoutes();
      await setup.goto();
      await setup.openAccountForm();
      await setup.openOAuthTab();

      // The sign-in saves the account itself, so the tab has no Create step.
      await setup.expectOAuthSetup();
    });
  });
}
