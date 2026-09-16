import { expect, test } from "@playwright/test";
import {
  OneDriveConnectorSetupPage,
  type OneDriveConfigRequest,
} from "@tests/e2e/pages/OneDriveConnectorSetupPage";

test.describe("OneDrive connector setup", () => {
  test("submits General scope with a client secret", async ({ page }) => {
    const setup = new OneDriveConnectorSetupPage(page);
    await setup.mockRoutes();
    await setup.goto();
    await setup.createClientSecretCredential();
    await setup.continueToConfiguration();
    await setup.selectSpecificScope("owner@example.com");
    await setup.selectGeneralScope();
    await setup.submitConnector("General OneDrive");
    await setup.expectCreated();

    expect(setup.credentialRequests).toEqual([
      {
        authenticationMethod: "client_secret",
        clientId: "client-id",
        directoryId: "directory-id",
        hasClientSecret: true,
        hasCertificatePassword: false,
      },
    ]);
    const expectedConfig: OneDriveConfigRequest = {
      connector_specific_config: {
        all_users: true,
        users: [],
      },
    };
    expect(setup.connectorRequests[0]).toEqual(expectedConfig);
  });

  test("submits Specific scope with a certificate", async ({ page }) => {
    const setup = new OneDriveConnectorSetupPage(page);
    await setup.mockRoutes();
    await setup.goto();
    await setup.createCertificateCredential();
    await setup.continueToConfiguration();
    await setup.selectSpecificScope("owner@example.com");
    await setup.submitConnector("Specific OneDrive");
    await setup.expectCreated();

    expect(setup.credentialRequests).toEqual([
      {
        authenticationMethod: "certificate",
        clientId: "client-id",
        directoryId: "directory-id",
        hasClientSecret: false,
        hasCertificatePassword: true,
        privateKeyField: "onedrive_private_key",
        privateKeyType: "onedrive_pfx_file",
      },
    ]);
    const expectedConfig: OneDriveConfigRequest = {
      connector_specific_config: {
        all_users: false,
        users: ["owner@example.com"],
      },
    };
    expect(setup.connectorRequests[0]).toEqual(expectedConfig);
  });

  test("sends empty Specific scope to backend validation", async ({ page }) => {
    const validationMessage = "Select all users or list at least one user.";
    const setup = new OneDriveConnectorSetupPage(page);
    await setup.mockRoutes(validationMessage);
    await setup.goto();
    await setup.createClientSecretCredential();
    await setup.continueToConfiguration();
    await setup.selectSpecificScope();
    await setup.submitConnector("Empty Specific OneDrive", 400);
    await setup.expectConfigurationError(validationMessage);

    const expectedConfig: OneDriveConfigRequest = {
      connector_specific_config: {
        all_users: false,
        users: [],
      },
    };
    expect(setup.connectorRequests[0]).toEqual(expectedConfig);
  });
});
