import { type Locator, type Page, expect } from "@playwright/test";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";

export type PolicyLabel = "Allow" | "Ask" | "Blocked";
export type IntegrationTab = "Overview" | "Configuration" | "Actions";

export interface OAuthSettings {
  authorizationUrl: string;
  tokenUrl: string;
  clientId: string;
  clientSecret: string;
  scopes: string;
}

/** One integration at /admin/integrations/[id]: Overview, Configuration and
 * Actions. */
export class AdminIntegrationDetailPage {
  readonly page: Page;
  readonly activePanel: Locator;
  readonly saveActionsButton: Locator;
  readonly refreshActionsButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.activePanel = page.locator('[role="tabpanel"][data-state="active"]');
    this.saveActionsButton = page.getByRole("button", {
      name: "Save",
      exact: true,
    });
    this.refreshActionsButton = page.getByRole("button", {
      name: "Refresh",
      exact: true,
    });
  }

  async goto(id: number, tab?: IntegrationTab): Promise<void> {
    const query = tab && tab !== "Overview" ? `?tab=${tab.toLowerCase()}` : "";
    await this.page.goto(`/admin/integrations/${id}${query}`);
  }

  async expectLoaded(name: string): Promise<void> {
    await expect(
      this.page.getByLabel("admin-page-title").getByText(name, { exact: true })
    ).toBeVisible();
  }

  async openTab(tab: IntegrationTab): Promise<void> {
    await this.page.getByRole("tab", { name: tab, exact: true }).click();
    await expect(
      this.page.getByRole("tab", { name: tab, exact: true })
    ).toHaveAttribute("aria-selected", "true");
  }

  policyButton(action: string, policy: PolicyLabel): Locator {
    return this.page
      .getByRole("group", { name: action, exact: true })
      .getByRole("button", { name: policy, exact: true });
  }

  async setActionPolicy(action: string, policy: PolicyLabel): Promise<void> {
    await this.policyButton(action, policy).click();
    await expect(this.policyButton(action, policy)).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  }

  async setDefaultPolicy(policy: PolicyLabel): Promise<void> {
    await this.setActionPolicy("Default for New Actions", policy);
  }

  async saveActions(): Promise<void> {
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/admin\/integrations\/\d+\/actions$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "PUT"
    );
    await this.saveActionsButton.click();
    expect((await response).ok()).toBeTruthy();
    await expect(this.saveActionsButton).toBeDisabled();
  }

  async refreshActions(): Promise<void> {
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/admin\/integrations\/\d+\/actions\/refresh$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "POST"
    );
    await this.refreshActionsButton.click();
    expect((await response).ok()).toBeTruthy();
  }

  /** Fills the credential fields of the organization connection by label and
   * connects. */
  async connectOrganization(fields: Record<string, string>): Promise<void> {
    await this.openTab("Configuration");
    for (const [label, value] of Object.entries(fields))
      await this.page.getByLabel(label, { exact: true }).fill(value);
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/admin\/integrations\/\d+\/organization-connection$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "PUT"
    );
    await this.page
      .getByRole("button", { name: "Connect", exact: true })
      .click();
    expect((await response).ok()).toBeTruthy();
    await expect(
      this.page.getByText("Connected", { exact: true })
    ).toBeVisible();
  }

  async expectSetByAdmin(action: string): Promise<void> {
    await expect(
      this.page
        .getByRole("group", { name: action, exact: true })
        .locator("xpath=../..")
        .getByText("Set by admin", { exact: true })
    ).toBeVisible();
  }

  field(label: string): Locator {
    return this.activePanel.getByLabel(label, { exact: true });
  }

  /** Saves the Configuration tab with the integration PATCH. */
  async saveConfiguration(): Promise<void> {
    const response = this.page.waitForResponse(
      (candidate) =>
        /^\/api\/admin\/integrations\/\d+$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "PATCH"
    );
    await this.activePanel
      .getByRole("button", { name: "Save", exact: true })
      .click();
    expect((await response).ok()).toBeTruthy();
  }

  /** Replaces the OpenAPI schema on the Configuration tab and saves it. */
  async replaceSchema(schema: string): Promise<void> {
    await this.openTab("Configuration");
    await this.activePanel
      .getByRole("textbox", { name: "OpenAPI Schema", exact: true })
      .fill(schema);
    await this.saveConfiguration();
  }

  async configureOAuth(settings: OAuthSettings): Promise<void> {
    await this.openTab("Configuration");
    await new AdminIntegrationsPage(this.page).selectSignIn(
      "Each user signs in",
      "OAuth",
      this.activePanel
    );
    await this.field("Authorization URL").fill(settings.authorizationUrl);
    await this.field("Token URL").fill(settings.tokenUrl);
    await this.field("Client ID").fill(settings.clientId);
    await this.field("Client Secret").fill(settings.clientSecret);
    await this.field("Scopes").fill(settings.scopes);
    await this.saveConfiguration();
  }

  async expectOAuthPersisted(
    settings: Pick<OAuthSettings, "authorizationUrl" | "tokenUrl" | "scopes">
  ): Promise<void> {
    await this.page.reload();
    await this.openTab("Configuration");
    await expect(this.field("Authorization URL")).toHaveValue(
      settings.authorizationUrl
    );
    await expect(this.field("Token URL")).toHaveValue(settings.tokenUrl);
    await expect(this.field("Scopes")).toHaveValue(
      settings.scopes
        .split(/[\s,]+/)
        .filter(Boolean)
        .join(" ")
    );
    await expect(
      this.activePanel.getByPlaceholder(
        "Saved. Enter a new secret to replace it."
      )
    ).toBeVisible();
  }
}
