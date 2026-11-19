import { type Locator, type Page, expect } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export type IntegrationKindLabel =
  | "MCP server"
  | "OpenAPI app"
  | "App"
  | "Custom app";

const TYPE_TITLES: Record<IntegrationKindLabel, string> = {
  "MCP server": "MCP Server",
  "OpenAPI app": "OpenAPI App",
  App: "App",
  "Custom app": "App",
};

/** The integration catalog at /admin/integrations and its Add page. */
export class AdminIntegrationsPage {
  readonly page: Page;
  readonly addButton: Locator;
  readonly addForm: Locator;
  readonly nameInput: Locator;
  readonly serverUrlInput: Locator;
  readonly searchInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.addButton = page.getByRole("link", { name: "Add", exact: true });
    this.addForm = page.locator("form").filter({
      has: page.getByRole("radiogroup", { name: "Type" }),
    });
    this.nameInput = this.addForm.getByRole("textbox", {
      name: "Name",
      exact: true,
    });
    this.serverUrlInput = this.addForm.getByRole("textbox", {
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

  /** Opens the Add page and picks the type. A custom app is an app that
   * starts from no preset, which the page picks first. */
  async openAdd(kind: IntegrationKindLabel): Promise<void> {
    await this.addButton.click();
    await expect(this.page).toHaveURL(/\/admin\/integrations\/new$/);
    await this.addForm
      .getByRole("radio", { name: TYPE_TITLES[kind], exact: true })
      .click();
  }

  async cancelAdd(): Promise<void> {
    await this.addForm
      .getByRole("button", { name: "Cancel", exact: true })
      .click();
    await expect(this.page).toHaveURL(/\/admin\/integrations$/);
  }

  async fillMcpServer(details: { name: string; url: string }): Promise<void> {
    await this.nameInput.fill(details.name);
    await this.serverUrlInput.fill(details.url);
  }

  /** Pastes an OpenAPI schema in its dialog and returns to the form. */
  async fillOpenApiSchema(schema: string): Promise<void> {
    await this.addForm
      .getByRole("button", { name: "Add schema", exact: true })
      .click();
    const dialog = this.page.getByRole("dialog");
    await dialog
      .getByPlaceholder("Enter your OpenAPI schema here")
      .fill(schema);
    await dialog.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(dialog).toBeHidden();
  }

  /** Picks the sign-in on the Add page, or in `scope` when given. */
  async selectSignIn(
    mode: string,
    method?: string,
    scope: Locator = this.addForm
  ): Promise<void> {
    await scope
      .getByRole("combobox", { name: "Sign-in Mode", exact: true })
      .click();
    await this.page.getByRole("option", { name: mode, exact: true }).click();
    if (!method) return;
    await scope
      .getByRole("combobox", { name: "Sign-in Method", exact: true })
      .click();
    await this.page.getByRole("option", { name: method, exact: true }).click();
  }

  /**
   * Waits for the server check of an OAuth MCP server. The check fills the
   * sign-in fields only while they are untouched, so call this before any
   * sign-in change.
   */
  async expectOAuthProbe(): Promise<void> {
    await expect(
      this.addForm.getByText("The server uses OAuth sign-in.", {
        exact: true,
      })
    ).toBeVisible();
  }

  /** Fills a manual OAuth client and keeps the discovered endpoint URLs. */
  async fillOAuthClient(clientId: string, clientSecret: string): Promise<void> {
    await this.addForm
      .getByRole("combobox", { name: "OAuth Client", exact: true })
      .click();
    await this.page
      .getByRole("option", { name: "Enter the client details", exact: true })
      .click();
    await this.addForm
      .getByRole("textbox", { name: "Client ID", exact: true })
      .fill(clientId);
    await this.addForm
      .getByLabel("Client Secret", { exact: true })
      .fill(clientSecret);
  }

  async chooseOwner(owner: "For me" | "For the organization"): Promise<void> {
    await this.addForm
      .getByRole("combobox", { name: "Owner", exact: true })
      .click();
    await this.page.getByRole("option", { name: owner, exact: true }).click();
  }

  /** Adds an OpenAPI app with no sign-in and returns its integration id. */
  async addOpenApiApp(schema: string, name: string): Promise<number> {
    await this.goto();
    await this.openAdd("OpenAPI app");
    await this.fillOpenApiSchema(schema);
    await expect(this.nameInput).toHaveValue(name);
    return this.submit();
  }

  /** Submits the Add form and returns the new integration id. */
  async submit(): Promise<number> {
    const response = this.page.waitForResponse(
      (candidate) =>
        new URL(candidate.url()).pathname === "/api/admin/integrations" &&
        candidate.request().method() === "POST"
    );
    await this.addForm
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

  /** A manager with no access of their own sees the reason on the row. */
  async expectNoAccess(name: string): Promise<void> {
    await expect(this.row(name).getByText(/^No access:/)).toBeVisible();
  }

  installSetting(name: string): Locator {
    return this.page.getByRole("combobox", {
      name: `Install setting of ${name}`,
      exact: true,
    });
  }

  /** Sets the company install setting from the list, for example
   * "Required" or "Available to install". */
  async setInstallSetting(name: string, label: string): Promise<void> {
    const select = this.installSetting(name);
    await expect(select).toBeEnabled();
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/admin\/integrations\/\d+\/installation-policy$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "PUT"
    );
    await select.click();
    await this.page
      .getByRole("option", { name: new RegExp(`^${label}`) })
      .click();
    expect((await response).ok()).toBeTruthy();
    await expect(select).toHaveValue(label);
  }
}
