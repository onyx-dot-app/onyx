import { type Page, type Locator, expect } from "@playwright/test";
import * as yup from "yup";
import { AdminPluginsPage } from "@tests/e2e/pages/AdminPluginsPage";

export class AdminMcpServersPage {
  readonly page: Page;
  readonly plugins: AdminPluginsPage;

  readonly nameInput: Locator;
  readonly descriptionInput: Locator;
  readonly serverUrlInput: Locator;
  readonly accessControlSelector: Locator;

  readonly authMethodSelector: Locator;
  readonly apiTokenInput: Locator;
  readonly oauthClientIdInput: Locator;
  readonly oauthClientSecretInput: Locator;
  readonly connectButton: Locator;

  readonly refreshToolsButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.plugins = new AdminPluginsPage(page);
    this.nameInput = page.getByLabel("Server Name", { exact: true });
    this.descriptionInput = page.getByLabel(/^Description/);
    this.serverUrlInput = page.getByLabel(/^MCP Server URL/);
    this.accessControlSelector = page.getByRole("combobox", {
      name: "Access control",
    });

    this.authMethodSelector = page.getByRole("combobox", {
      name: "Authentication Method",
      exact: true,
    });
    this.apiTokenInput = page.getByLabel("API Key", { exact: true });
    this.oauthClientIdInput = page.getByLabel("Client ID", { exact: true });
    this.oauthClientSecretInput = page.getByLabel(/^Client Secret/);
    this.connectButton = page.getByTestId("mcp-auth-connect-button");

    this.refreshToolsButton = page.getByRole("button", {
      name: "Refresh tools",
    });
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  async goto(): Promise<void> {
    await this.plugins.goto();
  }

  // ---------------------------------------------------------------------------
  // ---------------------------------------------------------------------------

  async openAddServerModal(): Promise<void> {
    await this.plugins.openAddMcp();
    await expect(this.serverUrlInput).toBeVisible();
  }

  async enterServerUrlAndContinue(url: string): Promise<void> {
    await this.serverUrlInput.fill(url);
    const next = this.page.getByRole("button", {
      name: "Continue",
      exact: true,
    });
    await expect(next).toBeEnabled({ timeout: 45_000 });
    await next.click();
    await expect(this.authMethodSelector).toBeVisible();
  }

  async discardSetup(): Promise<void> {
    await this.page
      .getByRole("button", { name: "Cancel", exact: true })
      .click();
    await expect(this.page.getByRole("dialog")).toBeHidden();
  }

  async expectAccessControlVisible(): Promise<void> {
    await expect(this.accessControlSelector).toBeVisible();
  }

  async fillServerDetails(details: {
    name: string;
    /** Restrict to this group. Required for a scoped manager: the backend
     *  refuses a public server outside the groups they manage. */
    group?: string;
  }): Promise<void> {
    await this.page.getByRole("button", { name: "Back", exact: true }).click();
    await this.nameInput.fill(details.name);
    await this.page
      .getByRole("button", { name: "Continue", exact: true })
      .click();
    if (details.group) {
      await this.restrictToGroup(details.group);
    }
  }

  async restrictToGroup(group: string): Promise<void> {
    await this.selectGroupAccess();
    const search = this.page.getByPlaceholder("Add user groups");
    await search.fill(group);
    await this.page
      .getByRole("option", {
        name: new RegExp(`^${group.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`),
      })
      .click();
  }

  async selectGroupAccess(): Promise<void> {
    await this.accessControlSelector.click();
    await this.page.getByRole("option", { name: /^User groups/ }).click();
    const search = this.page.getByPlaceholder("Add user groups");
    await expect(search).toBeVisible();
    await expect(search).toBeEnabled();
  }

  async connectAndWaitForCreation(): Promise<number> {
    const responsePromise = this.page.waitForResponse(
      (resp) =>
        new URL(resp.url()).pathname === "/api/admin/mcp/server" &&
        resp.request().method() === "POST"
    );
    await this.clickConnect();
    const response = await responsePromise;
    expect(response.ok(), await response.text()).toBeTruthy();
    const created = yup
      .object({ id: yup.number().integer().positive().required() })
      .validateSync(await response.json());
    return created.id;
  }

  // ---------------------------------------------------------------------------
  // ---------------------------------------------------------------------------

  async backToConnection(): Promise<void> {
    await this.page
      .getByRole("button", { name: "Connection", exact: true })
      .click();
    await expect(this.authMethodSelector).toBeVisible();
  }

  async selectAuthMethod(
    method: "OAuth" | "API Key" | "No authentication"
  ): Promise<void> {
    await this.authMethodSelector.click();
    await this.page
      .getByRole("option")
      .filter({ has: this.page.getByText(method, { exact: true }) })
      .click();
  }

  async selectApiKeyCredentials(which: "admin" | "per-user"): Promise<void> {
    const pattern = which === "admin" ? /Shared token/i : /Personal token/i;
    await this.page
      .getByRole("combobox", { name: "Credentials", exact: true })
      .click();
    await this.page.getByRole("option", { name: pattern }).click();
  }

  async fillApiToken(token: string): Promise<void> {
    await expect(this.apiTokenInput).toBeVisible();
    await this.apiTokenInput.click();
    await this.apiTokenInput.fill(token);
  }

  async fillOAuthCredentials(
    clientId: string,
    clientSecret: string
  ): Promise<void> {
    await this.page
      .getByRole("radio", { name: "Use your own OAuth client", exact: true })
      .click();
    await expect(this.oauthClientIdInput).toBeVisible();
    await this.oauthClientIdInput.fill(clientId);
    await this.oauthClientSecretInput.fill(clientSecret);
  }

  async clickConnect(): Promise<void> {
    await expect(this.connectButton).toBeVisible();
    await expect(this.connectButton).toBeEnabled();
    await this.connectButton.click();
  }

  // ---------------------------------------------------------------------------
  // Per-user multi-field template header builder
  // ---------------------------------------------------------------------------

  /**
   * The InputKeyValue wrapper for header rows. Inputs are labelled "Key N" /
   * "Value N" (1-indexed) because PerUserAuthConfig passes no placeholders.
   */
  get headerGroup(): Locator {
    return this.page.getByRole("group", {
      name: /Header Name and Header Value pairs/i,
    });
  }

  async expectFirstHeaderPrefilled(): Promise<void> {
    await this.expandCustomHeaders();
    await expect(this.headerGroup.getByLabel("Key 1")).toHaveValue(
      "Authorization"
    );
    await expect(this.headerGroup.getByLabel("Value 1")).toHaveValue(
      "Bearer {api_key}"
    );
  }

  async addHeaderRow(): Promise<void> {
    await this.expandCustomHeaders();
    await this.headerGroup
      .getByRole("button", { name: /Add Header Name and Header Value pair/i })
      .click();
  }

  async fillHeaderRow(
    index: number,
    name: string,
    value: string
  ): Promise<void> {
    await this.expandCustomHeaders();
    const nameInput = this.headerGroup.getByLabel(`Key ${index}`);
    const valueInput = this.headerGroup.getByLabel(`Value ${index}`);
    await expect(nameInput).toBeVisible();
    await nameInput.fill(name);
    await valueInput.fill(value);
  }

  private async expandAdvancedSettings(): Promise<void> {
    const expand = this.page.getByRole("button", {
      name: "Expand Advanced settings",
      exact: true,
    });
    if (await expand.isVisible()) {
      await expand.click();
    }
    await expect(
      this.page.getByRole("button", {
        name: "Fold Advanced settings",
        exact: true,
      })
    ).toBeVisible();
  }

  private async expandCustomHeaders(): Promise<void> {
    await this.expandAdvancedSettings();
    await expect(this.headerGroup).toBeVisible();
  }

  async fillOwnCredentials(credentials: {
    apiKey: string;
    username?: string;
  }): Promise<void> {
    const apiKeyInput = this.page.locator(
      'input[name="user_credentials.api_key"]'
    );
    await expect(apiKeyInput).toBeVisible();
    await apiKeyInput.fill(credentials.apiKey);
    if (credentials.username !== undefined) {
      const usernameInput = this.page.locator(
        'input[name="user_credentials.username"]'
      );
      await expect(usernameInput).toBeVisible();
      await usernameInput.fill(credentials.username);
    }
  }

  // ---------------------------------------------------------------------------
  // ---------------------------------------------------------------------------

  async expectServerDetail(serverName: string): Promise<void> {
    await expect(this.page).toHaveURL(/\/admin\/plugins\/mcp\/\d+(?:\?.*)?$/);
    await expect(this.page.getByRole("dialog")).toBeVisible();
    await expect(
      this.page.getByText(serverName, { exact: true }).first()
    ).toBeVisible();
    await this.page.getByRole("tab", { name: "Tools", exact: true }).click();
    await expect(this.refreshToolsButton).toBeEnabled();
  }

  async refreshTools(): Promise<void> {
    await expect(this.refreshToolsButton).toBeVisible();
    await this.refreshToolsButton.click();
    await expect(this.page.getByText("No tools available")).not.toBeVisible();
  }

  toolToggle(toolName: string): Locator {
    return this.page.getByRole("switch", {
      name: `tool-toggle-${toolName}`,
      exact: true,
    });
  }

  async setToolEnabled(toolName: string, enabled: boolean): Promise<void> {
    const toggle = this.toolToggle(toolName);
    await expect(toggle).toBeVisible();
    await expect(toggle).toBeEnabled();
    const desired = enabled ? "true" : "false";
    if ((await toggle.getAttribute("aria-checked")) === desired) return;
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", desired);
    const responsePromise = this.page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/admin/tool/status" &&
        response.request().method() === "PATCH"
    );
    const save = this.page.getByRole("button", {
      name: "Save Changes",
      exact: true,
    });
    await save.click();
    expect((await responsePromise).ok()).toBeTruthy();
    await expect(save).toBeDisabled();
    await expect(this.refreshToolsButton).toBeEnabled();
  }
}
