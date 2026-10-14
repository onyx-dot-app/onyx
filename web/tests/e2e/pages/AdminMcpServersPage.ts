/**
 * Page Object Model for the admin "MCP Actions" page (/admin/mcp-actions).
 *
 * Drives creation, authentication, and the server detail page. Most test setup
 * uses the API client; creation tests exercise these user-facing controls.
 */

import { type Page, type Locator, expect } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export class AdminMcpServersPage {
  readonly page: Page;

  // Server details page
  readonly addServerButton: Locator;
  readonly nameInput: Locator;
  readonly descriptionInput: Locator;
  readonly serverUrlInput: Locator;
  readonly submitButton: Locator;
  readonly accessControlSelector: Locator;

  // Authentication page
  readonly oauthMethodTab: Locator;
  readonly apiTokenInput: Locator;
  readonly oauthClientIdInput: Locator;
  readonly oauthClientSecretInput: Locator;
  readonly connectButton: Locator;

  // Server detail tools
  readonly refreshToolsButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.addServerButton = page.getByRole("button", {
      name: /Add MCP Server/i,
    });
    this.nameInput = page.locator("input#name");
    this.descriptionInput = page.locator("textarea#description");
    this.serverUrlInput = page.locator("input#server_url");
    this.submitButton = page.getByRole("button", {
      name: "Configure authentication",
      exact: true,
    });
    this.accessControlSelector = page.getByRole("combobox", {
      name: "Access control",
    });

    this.oauthMethodTab = page.getByRole("tab", { name: "OAuth", exact: true });
    this.apiTokenInput = page.locator('input[name="api_token"]');
    this.oauthClientIdInput = page.locator('input[name="oauth_client_id"]');
    this.oauthClientSecretInput = page.locator(
      'input[name="oauth_client_secret"]'
    );
    this.connectButton = page.getByTestId("mcp-auth-connect-button");

    this.refreshToolsButton = page.getByRole("button", {
      name: "Refresh tools",
    });
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  async goto(): Promise<void> {
    await this.page.goto(ADMIN_ROUTES.MCP_ACTIONS.path);
    await this.page.waitForURL(`**${ADMIN_ROUTES.MCP_ACTIONS.path}**`);
  }

  // ---------------------------------------------------------------------------
  // Server details page
  // ---------------------------------------------------------------------------

  async openAddServerModal(): Promise<void> {
    await this.addServerButton.click();
    await expect(this.nameInput).toBeVisible();
  }

  async expectAccessControlVisible(): Promise<void> {
    await expect(this.accessControlSelector).toBeVisible();
  }

  async fillServerDetails(details: {
    name: string;
    description?: string;
    url: string;
    /** Restrict to this group. Required for a scoped manager: the backend
     *  refuses a public server outside the groups they manage. */
    group?: string;
  }): Promise<void> {
    await this.nameInput.fill(details.name);
    if (details.description) {
      await this.descriptionInput.fill(details.description);
    }
    await this.serverUrlInput.fill(details.url);
    if (details.group) {
      await this.restrictToGroup(details.group);
    }
  }

  /** Scoped managers see only the group option; global holders can select it. */
  async restrictToGroup(group: string): Promise<void> {
    await this.accessControlSelector.click();
    await this.page.getByRole("option", { name: /^User groups/ }).click();
    const search = this.page.getByPlaceholder("Add user groups");
    await expect(search).toBeVisible();
    await expect(search).toBeEnabled();
    await search.fill(group);
    await this.page
      .getByRole("option", { name: new RegExp(`^${group}`) })
      .click();
  }

  /**
   * Save server details and continue to authentication in the same modal.
   * Returns the created server ID.
   */
  async submitAddServer(): Promise<number> {
    const responsePromise = this.page.waitForResponse(
      (resp) =>
        new URL(resp.url()).pathname === "/api/admin/mcp/server" &&
        resp.request().method() === "POST"
    );
    await this.submitButton.click();
    const response = await responsePromise;
    expect(response.ok(), await response.text()).toBeTruthy();
    const created = (await response.json()) as { id?: number };
    expect(created.id).toBeTruthy();
    await expect(this.oauthMethodTab).toBeVisible();
    return Number(created.id);
  }

  // ---------------------------------------------------------------------------
  // Authentication page
  // ---------------------------------------------------------------------------

  async backToServerDetails(): Promise<void> {
    await this.page
      .getByRole("button", { name: "Server configuration", exact: true })
      .click();
    await expect(this.nameInput).toBeVisible();
  }

  async continueToAuthentication(): Promise<void> {
    await this.submitButton.click();
    await expect(this.oauthMethodTab).toBeVisible();
  }

  async selectAuthMethod(method: "OAuth" | "API Key"): Promise<void> {
    await this.page.getByRole("tab", { name: method, exact: true }).click();
  }

  async selectApiKeyTab(which: "admin" | "per-user"): Promise<void> {
    const pattern = which === "admin" ? /Shared token/i : /Personal token/i;
    const tab = this.page.getByRole("tab", { name: pattern });
    await expect(tab).toBeVisible();
    await tab.click();
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
      .getByRole("tab", { name: "Use your own OAuth client" })
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

  /**
   * Click Connect and wait for the `servers/create` upsert (used by API-key /
   * per-user flows that validate credentials against the live server in-place).
   */
  async connectAndWaitForUpsert(): Promise<void> {
    const responsePromise = this.page.waitForResponse(
      (resp) =>
        resp.url().endsWith("/api/admin/mcp/servers/create") &&
        resp.request().method() === "POST"
    );
    await this.clickConnect();
    const response = await responsePromise;
    expect(response.ok()).toBeTruthy();
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
  // Server detail + tool toggles
  // ---------------------------------------------------------------------------

  async expectServerDetail(serverName: string): Promise<void> {
    await expect(this.page).toHaveURL(/\/admin\/mcp-actions\/\d+(?:\?.*)?$/);
    await expect(this.page.getByRole("dialog")).not.toBeVisible();
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
