import { type Locator, type Page, expect } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export type IntegrationKindLabel =
  | "MCP server"
  | "OpenAPI app"
  | "App"
  | "Custom app";

/** The integration catalog at /admin/integrations and its Add dialog. */
export class AdminIntegrationsPage {
  readonly page: Page;
  readonly addButton: Locator;
  readonly addDialog: Locator;
  readonly nameInput: Locator;
  readonly serverUrlInput: Locator;
  readonly searchInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.addButton = page.getByRole("button", { name: "Add", exact: true });
    this.addDialog = page.getByRole("dialog");
    this.nameInput = this.addDialog.getByRole("textbox", {
      name: "Name",
      exact: true,
    });
    this.serverUrlInput = this.addDialog.getByRole("textbox", {
      name: "Server URL",
      exact: true,
    });
    this.searchInput = page.getByRole("searchbox", {
      name: "Search integrations",
    });
  }

  async goto(): Promise<void> {
    await this.page.goto(ADMIN_ROUTES.INTEGRATIONS.path);
    await expect(this.page).toHaveURL(/\/admin\/integrations(?:\?.*)?$/);
    await expect(
      this.page
        .getByLabel("admin-page-title")
        .getByText("Integrations", { exact: true })
    ).toBeVisible();
    await expect(this.page.getByRole("table")).toBeVisible();
  }

  /** Opens Add and picks the kind; the OpenAPI kind opens its schema step. */
  async openAdd(kind: IntegrationKindLabel): Promise<void> {
    await this.addButton.click();
    await expect(this.addDialog).toBeVisible();
    await this.addDialog
      .getByRole("button", { name: kind, exact: true })
      .click();
  }

  async closeAddDialog(): Promise<void> {
    await this.addDialog
      .getByRole("button", { name: "Close", exact: true })
      .first()
      .click();
    await expect(this.addDialog).toBeHidden();
  }

  async fillMcpServer(details: { name: string; url: string }): Promise<void> {
    await this.nameInput.fill(details.name);
    await this.serverUrlInput.fill(details.url);
  }

  /** Pastes an OpenAPI schema and continues to the integration form. */
  async fillOpenApiSchema(schema: string): Promise<void> {
    await this.addDialog
      .getByPlaceholder("Enter your OpenAPI schema here")
      .fill(schema);
    await this.addDialog
      .getByRole("button", { name: "Continue", exact: true })
      .click();
    await expect(this.nameInput).toBeVisible();
  }

  async selectSignIn(mode: string, method?: string): Promise<void> {
    await this.addDialog
      .getByRole("combobox", { name: "Sign-in Mode", exact: true })
      .click();
    await this.page.getByRole("option", { name: mode, exact: true }).click();
    if (!method) return;
    await this.addDialog
      .getByRole("combobox", { name: "Sign-in Method", exact: true })
      .click();
    await this.page.getByRole("option", { name: method, exact: true }).click();
  }

  async chooseOwner(owner: "For me" | "For the organization"): Promise<void> {
    await this.addDialog
      .getByRole("combobox", { name: "Owner", exact: true })
      .click();
    await this.page.getByRole("option", { name: owner, exact: true }).click();
  }

  /** Submits the Add form and returns the new integration id. */
  async submit(): Promise<number> {
    const response = this.page.waitForResponse(
      (candidate) =>
        new URL(candidate.url()).pathname === "/api/admin/integrations" &&
        candidate.request().method() === "POST"
    );
    await this.addDialog
      .getByRole("button", { name: "Add", exact: true })
      .click();
    const created = await response;
    expect(created.ok(), await created.text()).toBeTruthy();
    await expect(this.page).toHaveURL(/\/admin\/integrations\/\d+(?:\?.*)?$/);
    const match = new URL(this.page.url()).pathname.match(/\/(\d+)$/);
    if (!match?.[1]) throw new Error("Integration detail URL has no id");
    return Number(match[1]);
  }

  row(name: string): Locator {
    return this.page
      .getByRole("row")
      .filter({ has: this.page.getByText(name, { exact: true }) });
  }

  async expectIntegrationVisible(name: string): Promise<void> {
    await expect(this.row(name)).toBeVisible();
  }

  async expectIntegrationAbsent(name: string | RegExp): Promise<void> {
    await expect(
      this.page.getByRole("row").filter({ hasText: name })
    ).toHaveCount(0);
  }

  async openIntegration(name: string): Promise<void> {
    await this.row(name).click();
    await expect(this.page).toHaveURL(/\/admin\/integrations\/\d+(?:\?.*)?$/);
  }
}
