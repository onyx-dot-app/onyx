import { expect, type Page, type Request } from "@playwright/test";

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
  privateKeyField?: string;
  privateKeyType?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseCredentialJson(value: unknown): OneDriveCredentialRequest {
  if (!isRecord(value)) {
    throw new Error("Credential request must be an object");
  }
  const credentialJson = value.credential_json;
  if (!isRecord(credentialJson)) {
    throw new Error("Credential JSON must be an object");
  }
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
  };
}

function getMultipartField(body: string, fieldName: string): string {
  const fieldMarker = `name="${fieldName}"`;
  const fieldStart = body.indexOf(fieldMarker);
  if (fieldStart < 0) {
    return "";
  }
  const valueStart = body.indexOf("\r\n\r\n", fieldStart);
  if (valueStart < 0) {
    return "";
  }
  const valueEnd = body.indexOf("\r\n--", valueStart);
  return body.slice(valueStart + 4, valueEnd < 0 ? undefined : valueEnd);
}

function parsePrivateKeyCredential(
  request: Request
): OneDriveCredentialRequest {
  const body = request.postData() ?? "";
  const credential = parseCredentialJson({
    credential_json: JSON.parse(getMultipartField(body, "credential_json")),
  });
  return {
    ...credential,
    privateKeyField: getMultipartField(body, "field_key"),
    privateKeyType: getMultipartField(body, "type_definition_key"),
  };
}

export class OneDriveConnectorSetupPage {
  readonly credentialRequests: OneDriveCredentialRequest[] = [];
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
    await this.page.route("**/api/manage/credential/private-key", (route) => {
      this.credentialRequests.push(parsePrivateKeyCredential(route.request()));
      return route.fulfill({ json: this.credentialResponse(42) });
    });
    await this.page.route("**/api/manage/credential", (route) => {
      this.credentialRequests.push(
        parseCredentialJson(route.request().postDataJSON())
      );
      return route.fulfill({ json: this.credentialResponse(41) });
    });
    await this.page.route("**/api/manage/admin/connector", async (route) => {
      const request: unknown = route.request().postDataJSON();
      if (!isRecord(request) || !isRecord(request.connector_specific_config)) {
        throw new Error("Connector request must include its configuration");
      }
      const config = request.connector_specific_config;
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
      return route.fulfill({ json: { id: 71 } });
    });
    await this.page.route("**/api/manage/connector/*/credential/*", (route) =>
      route.fulfill({ json: {} })
    );
  }

  async goto() {
    await this.page.goto("/admin/connectors/onedrive");
    await expect(
      this.page.locator('[aria-label="admin-page-title"]')
    ).toBeVisible();
  }

  async createClientSecretCredential() {
    await this.openCredentialForm();
    await this.fillCredentialIdentity();
    await this.page.getByTestId("onedrive_client_secret").fill("secret-value");
    await this.submitCredential();
  }

  async createCertificateCredential() {
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
    await this.submitCredential();
  }

  async expectConfigurationEnabled() {
    await expect(this.page.getByTestId("name")).toBeEnabled();
  }

  async selectSpecificScope(user?: string) {
    await this.page.getByRole("tab", { name: "Specific" }).click();
    if (!user) return;
    await this.page.getByRole("button", { name: "Add" }).click();
    await this.page.locator("#users").fill(user);
  }

  async selectGeneralScope() {
    await this.page.getByRole("tab", { name: "General" }).click();
  }

  async submitConnector(name: string) {
    await this.page.getByTestId("name").fill(name);
    const responsePromise = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/manage/admin/connector"
    );
    await this.page
      .getByRole("button", { name: "Connect", exact: true })
      .click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
  }

  async submitInvalidConnector(name: string, message: string) {
    await this.page.getByTestId("name").fill(name);
    await expect(
      this.page.getByRole("button", { name: "Connect", exact: true })
    ).toBeDisabled();
    await expect(this.page.getByText(message)).toBeVisible();
  }

  async expectCreated() {
    await expect(this.page).toHaveURL(/\/admin\/indexing-status/);
  }

  private async openCredentialForm() {
    await this.page.getByRole("button", { name: "Create New" }).click();
    await expect(this.page.getByTestId("onedrive_client_id")).toBeVisible();
  }

  private async fillCredentialIdentity() {
    await this.page
      .getByRole("dialog")
      .getByTestId("name")
      .fill("OneDrive test credential");
    await this.page.getByTestId("onedrive_client_id").fill("client-id");
    await this.page.getByTestId("onedrive_directory_id").fill("directory-id");
  }

  private async submitCredential() {
    const responsePromise = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        [
          "/api/manage/credential",
          "/api/manage/credential/private-key",
        ].includes(new URL(response.url()).pathname)
    );
    await this.page
      .getByRole("dialog")
      .getByRole("button", { name: "Create", exact: true })
      .click();
    const response = await responsePromise;
    expect(response.ok()).toBeTruthy();
    await expect(this.page.getByRole("dialog")).toBeHidden();
  }

  private credentialResponse(id: number) {
    const timestamp = new Date(0).toISOString();
    return {
      id,
      credential: {
        id,
        credential_json: {},
        admin_public: true,
        source: "onedrive",
        name: "OneDrive test credential",
        user_id: null,
        user_email: null,
        time_created: timestamp,
        time_updated: timestamp,
      },
    };
  }
}
