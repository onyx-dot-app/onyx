import { type Locator, type Page, expect } from "@playwright/test";
import { AdminPluginsPage } from "@tests/e2e/pages/AdminPluginsPage";

interface OAuthSettings {
  authorizationUrl: string;
  tokenUrl: string;
  clientId: string;
  clientSecret: string;
  scopes: string;
}

export class AdminOpenApiPluginPage {
  readonly page: Page;
  readonly plugins: AdminPluginsPage;
  readonly detailDialog: Locator;

  constructor(page: Page) {
    this.page = page;
    this.plugins = new AdminPluginsPage(page);
    this.detailDialog = page.getByRole("dialog");
  }

  async createFromSchema(schema: string, name: string): Promise<number> {
    await this.plugins.goto();
    await this.plugins.openAddOpenApi();
    const dialog = this.page.getByRole("dialog", {
      name: "Add an OpenAPI plugin",
      exact: true,
    });
    await expect(dialog).toBeVisible();
    await dialog
      .getByPlaceholder("Enter your OpenAPI schema here")
      .fill(schema);
    await dialog.getByRole("button", { name: "Continue", exact: true }).click();
    await this.page
      .getByRole("dialog", { name: `Connect to ${name}`, exact: true })
      .getByRole("button", { name: "Add Action", exact: true })
      .click();
    await this.expectDetail(name);
    const match = new URL(this.page.url()).pathname.match(/\/openapi\/(\d+)$/);
    if (!match?.[1])
      throw new Error("OpenAPI plugin detail URL has no tool ID");
    return Number(match[1]);
  }

  async expectDetail(name: string): Promise<void> {
    await expect(this.page).toHaveURL(
      /\/admin\/plugins\/openapi\/\d+(?:\?.*)?$/
    );
    await expect(
      this.page.getByRole("dialog").getByText(name, { exact: true })
    ).toBeVisible();
  }

  async configureOAuth(settings: OAuthSettings): Promise<void> {
    const dialog = this.detailDialog;
    await expect(dialog).toBeVisible();
    await dialog
      .getByRole("tab", { name: "Authentication", exact: true })
      .click();
    await dialog.getByRole("combobox").click();
    await this.page.getByRole("option", { name: /^OAuth Each user/ }).click();
    await dialog
      .getByLabel("Authorization URL", { exact: true })
      .fill(settings.authorizationUrl);
    await dialog
      .getByLabel("Token URL", { exact: true })
      .fill(settings.tokenUrl);
    await dialog
      .getByLabel("OAuth Client ID", { exact: true })
      .fill(settings.clientId);
    await dialog
      .getByLabel("OAuth Client Secret", { exact: true })
      .fill(settings.clientSecret);
    await dialog.getByLabel(/^Scopes/).fill(settings.scopes);
    const save = dialog.getByRole("button", {
      name: "Save Changes",
      exact: true,
    });
    await save.click();
    await expect(save).toBeDisabled();
    await expect(dialog).toBeVisible();
  }

  async expectOAuthPersisted(
    settings: Pick<OAuthSettings, "authorizationUrl" | "tokenUrl" | "scopes">
  ): Promise<void> {
    await this.page.reload();
    const dialog = this.detailDialog;
    await dialog
      .getByRole("tab", { name: "Authentication", exact: true })
      .click();
    await expect(
      dialog.getByLabel("Authorization URL", { exact: true })
    ).toHaveValue(settings.authorizationUrl);
    await expect(dialog.getByLabel("Token URL", { exact: true })).toHaveValue(
      settings.tokenUrl
    );
    await expect(dialog.getByLabel(/^Scopes/)).toHaveValue(settings.scopes);
    await expect(
      dialog.getByLabel("OAuth Client ID", { exact: true })
    ).toHaveValue("********");
    // The stored client secret shows as a tag; the input itself stays empty.
    await expect(
      dialog.getByLabel("OAuth Client Secret", { exact: true })
    ).toHaveValue("");
    await expect(dialog.getByText("********", { exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).toBeHidden();
  }
}
