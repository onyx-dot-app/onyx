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
    await setup.expectConfigurationEnabled();
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
    await setup.expectConfigurationEnabled();
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
        users: ["owner@example.com"],
      },
    };
    expect(setup.connectorRequests[0]).toEqual(expectedConfig);
  });

  test("requires a user for Specific scope", async ({ page }) => {
    const validationMessage = "Add at least one user for Specific scope";
    const setup = new OneDriveConnectorSetupPage(page);
    await setup.mockRoutes();
    await setup.goto();
    await setup.createClientSecretCredential();
    await setup.expectConfigurationEnabled();
    await setup.selectSpecificScope();
    await setup.submitInvalidConnector(
      "Empty Specific OneDrive",
      validationMessage
    );
    expect(setup.connectorRequests).toEqual([]);
  });
});
