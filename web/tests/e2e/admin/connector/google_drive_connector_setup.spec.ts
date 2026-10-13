import { expect, test } from "@playwright/test";
import {
  GoogleDriveConnectorSetupPage,
  SERVICE_ACCOUNT_KEY,
} from "@tests/e2e/pages/GoogleDriveConnectorSetupPage";

test.describe("Google Drive connector setup", () => {
  test("submits a service account typed into the form", async ({ page }) => {
    const setup = new GoogleDriveConnectorSetupPage(page);
    await setup.mockRoutes();
    await setup.goto();
    await setup.openAccountForm();

    // The email starts empty: nothing fills it in.
    await expect(page.getByTestId("google_primary_admin")).toHaveValue("");

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
  });

  test("signs in with OAuth from its own tab", async ({ page }) => {
    const setup = new GoogleDriveConnectorSetupPage(page);
    await setup.mockRoutes();
    await setup.goto();
    await setup.openAccountForm();
    await setup.tab("OAuth").click();

    // The sign-in saves the account itself, so the tab has no Create step.
    await expect(
      page.getByRole("button", { name: "Authenticate with Google Drive" })
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Create", exact: true })
    ).toHaveCount(0);
  });
});
