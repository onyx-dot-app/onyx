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
  /** The tool `createFromSchema` made, to reopen its modal later. */
  private toolId: number | null = null;

  constructor(page: Page) {
    this.page = page;
    this.plugins = new AdminPluginsPage(page);
    this.detailDialog = page.getByRole("dialog");
  }

  async createFromSchema(schema: string, name: string): Promise<number> {
    await this.plugins.goto();
    await this.plugins.openAddOpenApi();
    // The header's description is part of the dialog's name.
    const dialog = this.page.getByRole("dialog", {
      name: /^Add OpenAPI action\b/,
    });
    await expect(dialog).toBeVisible();
    await dialog
      .getByPlaceholder("Enter your OpenAPI schema here")
      .fill(schema);
    await dialog.getByRole("button", { name: "Continue", exact: true }).click();
    // Continue moves the same dialog to its Authentication tab. Add closes
    // the dialog, so the new tool's id comes from the create response.
    const created = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/admin/tool/custom"
    );
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    const body: unknown = await (await created).json();
    const toolId =
      typeof body === "object" && body !== null && "id" in body
        ? Number(body.id)
        : NaN;
    if (!Number.isInteger(toolId))
      throw new Error("OpenAPI plugin create response has no tool ID");
    await expect(dialog).toBeHidden();
    this.toolId = toolId;
    await this.open();
    await this.expectDetail(name);
    return toolId;
  }

  /** Opens the created tool's modal; the one-time `plugin` param opens it. */
  async open(): Promise<void> {
    if (this.toolId === null)
      throw new Error("No OpenAPI plugin was created to open");
    await this.page.goto(`/admin/plugins?plugin=openapi:${this.toolId}`);
  }

  async expectDetail(name: string): Promise<void> {
    await expect(this.page).toHaveURL(/\/admin\/plugins(?:\?.*)?$/);
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
      name: "Update",
      exact: true,
    });
    await save.click();
    // A successful save closes the modal.
    await expect(dialog).toBeHidden();
  }

  async expectOAuthPersisted(
    settings: Pick<OAuthSettings, "authorizationUrl" | "tokenUrl" | "scopes">
  ): Promise<void> {
    await this.open();
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
    await expect(
      dialog.getByLabel("OAuth Client Secret", { exact: true })
    ).toHaveValue("********");
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).toBeHidden();
  }
}
