import { type Locator, type Page, expect } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

/** The rows of the Add menu on an integrations list. */
export type AddIntegrationKind = "MCP Server" | "Custom API";

/** The integration catalog at /admin/integrations and its add modal. */
export class AdminIntegrationsPage {
  readonly page: Page;
  readonly addButton: Locator;
  readonly addForm: Locator;
  readonly nameInput: Locator;
  readonly serverUrlInput: Locator;
  readonly apiUrlInput: Locator;
  readonly endpointsInput: Locator;
  readonly searchInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.addButton = page.getByRole("button", { name: "Add", exact: true });
    this.addForm = page.getByRole("dialog");
    this.nameInput = this.addForm.getByRole("textbox", {
      name: "Name",
      exact: true,
    });
    this.serverUrlInput = this.addForm.getByRole("textbox", {
      name: "Server URL",
      exact: true,
    });
    this.apiUrlInput = this.addForm.getByRole("textbox", {
      name: "URL",
      exact: true,
    });
    this.endpointsInput = this.addForm.getByRole("textbox", {
      name: "Endpoints",
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

  /** Opens the add modal from a row of the Add menu. */
  async openAdd(kind: AddIntegrationKind): Promise<void> {
    await this.addButton.click();
    await this.page.getByRole("menuitem", { name: kind, exact: true }).click();
    await expect(this.addForm).toBeVisible();
  }

  /** Opens the catalog from the section at the foot of the list. */
  async openCatalog(): Promise<void> {
    await this.page
      .getByRole("button", { name: "Browse", exact: true })
      .click();
    await expect(
      this.page.getByRole("dialog", { name: /^Add from Catalog/ })
    ).toBeVisible();
  }

  async cancelAdd(): Promise<void> {
    await this.addForm
      .getByRole("button", { name: "Cancel", exact: true })
      .click();
    await expect(this.addForm).toBeHidden();
  }

  /** Step 1 to step 2: Onyx checks the URL, then shows the sign-in. */
  async continueAdd(): Promise<void> {
    await this.addForm
      .getByRole("button", { name: "Continue", exact: true })
      .click();
    await expect(
      this.addForm.getByRole("button", { name: "Add", exact: true })
    ).toBeVisible();
  }

  /** Fills step 1 of an MCP server and waits for the server check. */
  async fillMcpServer(details: { name: string; url: string }): Promise<void> {
    await this.nameInput.fill(details.name);
    await this.serverUrlInput.fill(details.url);
    await this.continueAdd();
  }

  /** Uploads a spec file in step 1 of a custom API. */
  async uploadSpec(fileName: string, spec: string): Promise<void> {
    await this.addForm
      .getByLabel("Upload openapi.json, openapi.yaml or schema.graphql", {
        exact: true,
      })
      .setInputFiles({
        name: fileName,
        mimeType: fileName.endsWith(".json")
          ? "application/json"
          : "text/plain",
        buffer: Buffer.from(spec),
      });
    await expect(this.addForm.getByText(`Spec: ${fileName}`)).toBeVisible();
  }

  /** Adds a custom REST API by its base URL, with one endpoint per line. */
  async fillCustomApi(details: {
    name: string;
    baseUrl: string;
    endpoints: string[];
  }): Promise<void> {
    await this.nameInput.fill(details.name);
    await this.apiUrlInput.fill(details.baseUrl);
    await this.continueAdd();
    await expect(
      this.addForm.getByText("REST API with no spec.", { exact: false })
    ).toBeVisible();
    await this.endpointsInput.fill(details.endpoints.join("\n"));
  }

  /** Adds a custom GraphQL API: an endpoint URL and an uploaded schema. */
  async fillGraphQLApi(details: {
    name: string;
    endpointUrl: string;
    schema: string;
  }): Promise<void> {
    await this.nameInput.fill(details.name);
    await this.apiUrlInput.fill(details.endpointUrl);
    await this.uploadSpec("schema.graphql", details.schema);
    await this.continueAdd();
    await expect(this.addForm.getByText(/^GraphQL API, /)).toBeVisible();
  }

  /** Opens the Advanced section of step 2 when it is closed. */
  async openAdvanced(): Promise<void> {
    const toggle = this.addForm.getByRole("button", {
      name: /^(Expand|Fold) Advanced$/,
    });
    if ((await toggle.getAttribute("aria-expanded")) !== "true")
      await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
  }

  /** Picks the sign-in in the add modal, or in `scope` when given. In the
   * modal, the method is under Advanced. */
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
    if (scope === this.addForm) await this.openAdvanced();
    await scope
      .getByRole("combobox", { name: "Sign-in Method", exact: true })
      .click();
    await this.page.getByRole("option", { name: method, exact: true }).click();
  }

  /**
   * Checks that the server check found OAuth sign-in. The check runs on
   * Continue, before step 2 shows.
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
    await this.openAdvanced();
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
    await this.openAdvanced();
    await this.addForm
      .getByRole("combobox", { name: "Owner", exact: true })
      .click();
    await this.page.getByRole("option", { name: owner, exact: true }).click();
  }

  /** Adds a custom REST API from an uploaded spec, with no sign-in, and
   * returns its integration id. */
  async addOpenApiApp(schema: string, name: string): Promise<number> {
    await this.goto();
    await this.openAdd("Custom API");
    await this.nameInput.fill(name);
    await this.uploadSpec("openapi.json", schema);
    await this.continueAdd();
    await expect(
      this.addForm.getByText(/^REST API, \d+ endpoints?$/)
    ).toBeVisible();
    return this.submit();
  }

  /** Submits the add modal and returns the new integration id. */
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
