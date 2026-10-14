import { expect, type Page } from "@playwright/test";
import {
  mockPassingConnectorChecks,
  runConnectorChecks,
} from "@tests/e2e/utils/connectorChecks";

/** A service-account key with every field the backend requires. */
export const SERVICE_ACCOUNT_KEY = JSON.stringify({
  type: "service_account",
  project_id: "e2e-project",
  private_key_id: "e2e-key-id",
  private_key: "-----BEGIN PRIVATE KEY-----\ne2e\n-----END PRIVATE KEY-----\n",
  client_email: "indexer@e2e-project.iam.gserviceaccount.com",
  client_id: "123",
  auth_uri: "https://accounts.google.com/o/oauth2/auth",
  token_uri: "https://oauth2.googleapis.com/token",
  auth_provider_x509_cert_url: "https://www.googleapis.com/oauth2/v1/certs",
  client_x509_cert_url:
    "https://www.googleapis.com/robot/v1/metadata/x509/indexer",
  universe_domain: "googleapis.com",
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export class GoogleDriveConnectorSetupPage {
  /** The typed account of the latest check run. */
  credentialJson: Record<string, unknown> | null = null;
  /** The connector config of each create request. */
  readonly connectorConfigs: Record<string, unknown>[] = [];
  /**
   * The account each create request names: the draft's id, plus its
   * values when they changed.
   */
  readonly createCredentials: {
    credential_id: unknown;
    credential_json: unknown;
  }[] = [];

  constructor(private readonly page: Page) {}

  async mockRoutes() {
    await this.page.route(
      "**/api/manage/admin/similar-credentials/google_drive*",
      (route) => route.fulfill({ json: [] })
    );
    await this.page.route(
      "**/api/connector/oauth/details/google_drive",
      (route) =>
        route.fulfill({
          json: {
            oauth_enabled: false,
            supports_manual_credentials: true,
            additional_kwargs: [],
          },
        })
    );
    await this.page.route(
      "**/api/manage/admin/connector-with-credential",
      (route) => {
        const request: unknown = route.request().postDataJSON();
        const connector = isRecord(request) ? request.connector : undefined;
        if (
          !isRecord(connector) ||
          !isRecord(connector.connector_specific_config)
        ) {
          throw new Error("Connector request must include its configuration");
        }
        this.connectorConfigs.push(connector.connector_specific_config);
        this.createCredentials.push({
          credential_id: isRecord(request) ? request.credential_id : undefined,
          credential_json: isRecord(request)
            ? request.credential_json
            : undefined,
        });
        return route.fulfill({
          json: { success: true, message: "", data: 71 },
        });
      }
    );
    await mockPassingConnectorChecks(this.page);
    // A typed account travels with the check run, which saves it as a draft.
    // Registered last, so it sees the run first and hands it to the mock.
    await this.page.route(
      "**/api/manage/admin/connector-checks/runs",
      (route) => {
        const request: unknown = route.request().postDataJSON();
        if (isRecord(request) && isRecord(request.credential_json)) {
          this.credentialJson = request.credential_json;
        }
        return route.fallback();
      }
    );
  }

  async goto() {
    await this.page.goto("/admin/connectors/google_drive");
    await expect(
      this.page.locator('[aria-label="admin-page-title"]')
    ).toBeVisible();
  }

  /**
   * Opens the new-account card. It starts open when there is no saved
   * account, so it is clicked only while closed; retried in case its starting
   * state settles after the first look.
   */
  async openAccountForm() {
    const card = this.page.getByRole("button", {
      name: "New Google Drive Account",
    });
    await expect(async () => {
      if ((await card.getAttribute("aria-expanded")) !== "true") {
        await card.click();
      }
      await expect(card).toHaveAttribute("aria-expanded", "true", {
        timeout: 1_000,
      });
    }).toPass();
  }

  async expectPrimaryAdminEmpty() {
    await expect(this.primaryAdmin).toHaveValue("");
  }

  async openOAuthTab() {
    await this.tab("OAuth").click();
  }

  /** The OAuth tab: its sign-in saves the account, so there is no Create. */
  async expectOAuthSetup() {
    await expect(
      this.page.getByRole("button", { name: "Authenticate with Google Drive" })
    ).toBeDisabled();
    await expect(
      this.page.getByRole("button", { name: "Create", exact: true })
    ).toHaveCount(0);
  }

  async fillServiceAccount(primaryAdmin: string) {
    await this.tab("Service Account").click();
    await this.primaryAdmin.fill(primaryAdmin);
    await this.accountForm
      .locator('input[type="file"]')
      .first()
      .setInputFiles({
        name: "service-account.json",
        mimeType: "application/json",
        buffer: Buffer.from(SERVICE_ACCOUNT_KEY),
      });
  }

  /** Run the connector checks and wait for the configuration to unlock. */
  async runChecks() {
    await runConnectorChecks(this.page);
  }

  async submitConnector(name: string) {
    await this.page.getByTestId("connector-name").fill(name);
    const responsePromise = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname ===
          "/api/manage/admin/connector-with-credential"
    );
    await this.page
      .getByRole("button", { name: "Create Connector", exact: true })
      .click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
  }

  async expectCreated() {
    await expect(this.page).toHaveURL(/\/admin\/indexing-status/);
  }

  private tab(name: "Service Account" | "OAuth") {
    return this.accountForm.getByRole("tab", { name, exact: true });
  }

  private get primaryAdmin() {
    return this.page.getByTestId("google_primary_admin");
  }

  /** The new-account card's fold. */
  private get accountForm() {
    return this.page.getByTestId("credential-form");
  }
}
