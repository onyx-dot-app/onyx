import { expect, type Page } from "@playwright/test";
import {
  mockPassingConnectorChecks,
  runConnectorChecks,
} from "@tests/e2e/utils/connectorChecks";

export interface OneDriveConfigRequest {
  connector_specific_config: {
    users: string[];
  };
}

export interface OneDriveCredentialRequest {
  authenticationMethod: string;
  clientId: string;
  directoryId: string;
  hasClientSecret: boolean;
  hasCertificatePassword: boolean;
  /** The certificate, as the base64 text the account stores. */
  privateKey?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** The draft account a check run sends, or `null` for a saved account. */
function parseDraftCredential(
  value: unknown
): OneDriveCredentialRequest | null {
  if (!isRecord(value) || !isRecord(value.credential_json)) return null;
  const credentialJson = value.credential_json;
  const privateKey = credentialJson.onedrive_private_key;
  return {
    authenticationMethod: String(credentialJson.authentication_method ?? ""),
    clientId: String(credentialJson.onedrive_client_id ?? ""),
    directoryId: String(credentialJson.onedrive_directory_id ?? ""),
    hasClientSecret:
      typeof credentialJson.onedrive_client_secret === "string" &&
      credentialJson.onedrive_client_secret.length > 0,
    hasCertificatePassword:
      typeof credentialJson.onedrive_certificate_password === "string" &&
      credentialJson.onedrive_certificate_password.length > 0,
    ...(typeof privateKey === "string" ? { privateKey } : {}),
  };
}

export class OneDriveConnectorSetupPage {
  /** The draft account of the latest check run. */
  credentialRequest: OneDriveCredentialRequest | null = null;
  readonly connectorRequests: OneDriveConfigRequest[] = [];

  constructor(private readonly page: Page) {}

  async mockRoutes(connectorError?: string) {
    await this.page.route(
      "**/api/manage/admin/similar-credentials/onedrive*",
      (route) => route.fulfill({ json: [] })
    );
    await this.page.route("**/api/connector/oauth/details/onedrive", (route) =>
      route.fulfill({
        json: {
          oauth_enabled: false,
          supports_manual_credentials: true,
          additional_kwargs: [],
        },
      })
    );
    // Create makes the connector and pairs it in one request.
    await this.page.route(
      "**/api/manage/admin/connector-with-credential",
      async (route) => {
        const request: unknown = route.request().postDataJSON();
        const connector = isRecord(request) ? request.connector : undefined;
        if (
          !isRecord(connector) ||
          !isRecord(connector.connector_specific_config)
        ) {
          throw new Error("Connector request must include its configuration");
        }
        const config = connector.connector_specific_config;
        if (
          !Array.isArray(config.users) ||
          !config.users.every((user) => typeof user === "string")
        ) {
          throw new Error("OneDrive scope configuration has invalid types");
        }
        this.connectorRequests.push({
          connector_specific_config: {
            users: config.users,
          },
        });
        if (connectorError) {
          return route.fulfill({
            status: 400,
            json: { detail: connectorError },
          });
        }
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
        const draft = parseDraftCredential(route.request().postDataJSON());
        if (draft) this.credentialRequest = draft;
        return route.fallback();
      }
    );
  }

  async goto() {
    await this.page.goto("/admin/connectors/onedrive");
    await expect(
      this.page.locator('[aria-label="admin-page-title"]')
    ).toBeVisible();
  }

  async fillClientSecretCredential() {
    await this.openCredentialForm();
    await this.fillCredentialIdentity();
    await this.page.getByTestId("onedrive_client_secret").fill("secret-value");
  }

  async fillCertificateCredential() {
    await this.openCredentialForm();
    await this.page.getByRole("tab", { name: "Certificate" }).click();
    await this.fillCredentialIdentity();
    await this.page
      .getByTestId("onedrive_certificate_password")
      .fill("certificate-password");
    await this.page.locator('input[type="file"]').setInputFiles({
      name: "onedrive.pfx",
      mimeType: "application/x-pkcs12",
      buffer: Buffer.from("test-pfx"),
    });
  }

  /** Run the connector checks and wait for the configuration to unlock. */
  async runChecks() {
    await runConnectorChecks(this.page);
  }

  async selectSpecificScope(user?: string) {
    await this.page.getByRole("tab", { name: "Specific" }).click();
    if (!user) return;
    // The Excluded Paths list has its own add button outside the tab, so the
    // users list is found inside the Specific tab's panel.
    const panel = this.page.getByRole("tabpanel", { name: "Specific" });
    await panel.getByRole("button", { name: "Add New" }).click();
    await panel.getByRole("textbox").last().fill(user);
  }

  async selectGeneralScope() {
    await this.page.getByRole("tab", { name: "General" }).click();
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

  async submitInvalidConnector(name: string, message: string) {
    await this.page.getByTestId("connector-name").fill(name);
    await expect(
      this.page.getByRole("button", { name: "Create Connector", exact: true })
    ).toBeDisabled();
    await expect(this.page.getByText(message)).toBeVisible();
  }

  async expectCreated() {
    await expect(this.page).toHaveURL(/\/admin\/indexing-status/);
  }

  /**
   * Opens the new-account card. It starts open when there is no saved
   * account, so it is clicked only while closed; retried in case its starting
   * state settles after the first look.
   */
  private async openCredentialForm() {
    const card = this.page.getByRole("button", {
      name: "New OneDrive Account",
    });
    await expect(async () => {
      if ((await card.getAttribute("aria-expanded")) !== "true") {
        await card.click();
      }
      await expect(card).toHaveAttribute("aria-expanded", "true", {
        timeout: 1_000,
      });
    }).toPass();
    await expect(this.page.getByTestId("onedrive_client_id")).toBeVisible();
  }

  private async fillCredentialIdentity() {
    await this.page.getByTestId("onedrive_client_id").fill("client-id");
    await this.page.getByTestId("onedrive_directory_id").fill("directory-id");
  }
}
