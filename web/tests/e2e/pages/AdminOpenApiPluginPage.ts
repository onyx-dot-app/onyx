import { type Locator, type Page, expect } from "@playwright/test";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";
import { AdminIntegrationDetailPage } from "@tests/e2e/pages/AdminIntegrationDetailPage";

interface OAuthSettings {
  authorizationUrl: string;
  tokenUrl: string;
  clientId: string;
  clientSecret: string;
  scopes: string;
}

/** An OpenAPI app on the integration pages: the Add flow and the sign-in
 * settings of its Configuration tab. */
export class AdminOpenApiPluginPage {
  readonly page: Page;
  readonly integrations: AdminIntegrationsPage;
  readonly detail: AdminIntegrationDetailPage;

  constructor(page: Page) {
    this.page = page;
    this.integrations = new AdminIntegrationsPage(page);
    this.detail = new AdminIntegrationDetailPage(page);
  }

  /** Adds the app with no sign-in and returns its integration id. */
  async createFromSchema(schema: string, name: string): Promise<number> {
    await this.integrations.goto();
    await this.integrations.openAdd("OpenAPI app");
    await this.integrations.fillOpenApiSchema(schema);
    await expect(this.integrations.nameInput).toHaveValue(name);
    const id = await this.integrations.submit();
    await this.expectDetail(name);
    return id;
  }

  async expectDetail(name: string): Promise<void> {
    await expect(this.page).toHaveURL(/\/admin\/integrations\/\d+(?:\?.*)?$/);
    await this.detail.expectLoaded(name);
  }

  field(name: string): Locator {
    return this.page.getByLabel(name, { exact: true });
  }

  async configureOAuth(settings: OAuthSettings): Promise<void> {
    await this.detail.openTab("Configuration");
    await this.page
      .getByRole("combobox", { name: "Sign-in Mode", exact: true })
      .click();
    await this.page
      .getByRole("option", { name: "Each user signs in", exact: true })
      .click();
    await this.page
      .getByRole("combobox", { name: "Sign-in Method", exact: true })
      .click();
    await this.page.getByRole("option", { name: "OAuth", exact: true }).click();
    await this.field("Authorization URL").fill(settings.authorizationUrl);
    await this.field("Token URL").fill(settings.tokenUrl);
    await this.field("Client ID").fill(settings.clientId);
    await this.field("Client Secret").fill(settings.clientSecret);
    await this.field("Scopes").fill(settings.scopes);
    const saved = this.page.waitForResponse(
      (response) =>
        /^\/api\/admin\/integrations\/\d+$/.test(
          new URL(response.url()).pathname
        ) && response.request().method() === "PATCH"
    );
    await this.page.getByRole("button", { name: "Save", exact: true }).click();
    expect((await saved).ok()).toBeTruthy();
  }

  async expectOAuthPersisted(
    settings: Pick<OAuthSettings, "authorizationUrl" | "tokenUrl" | "scopes">
  ): Promise<void> {
    await this.page.reload();
    await this.detail.openTab("Configuration");
    await expect(this.field("Authorization URL")).toHaveValue(
      settings.authorizationUrl
    );
    await expect(this.field("Token URL")).toHaveValue(settings.tokenUrl);
    // Scopes come back split and joined by spaces.
    await expect(this.field("Scopes")).toHaveValue(
      settings.scopes
        .split(/[\s,]+/)
        .filter(Boolean)
        .join(" ")
    );
    await expect(
      this.page.getByPlaceholder("Saved. Enter a new secret to replace it.")
    ).toBeVisible();
  }
}
