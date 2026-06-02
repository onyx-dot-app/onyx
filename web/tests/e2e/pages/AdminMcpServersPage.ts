/**
 * Page Object Model for the admin "MCP Actions" page (/admin/actions/mcp).
 *
 * Drives the Add-Server modal and the auth-configuration modal (OAuth / API Key
 * shared / API Key per-user). Used by the UI "create-flow" tests we deliberately
 * keep — most other setup is done via the API client instead.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class AdminMcpServersPage {
  readonly page: Page;

  // Add-server modal
  readonly addServerButton: Locator;
  readonly nameInput: Locator;
  readonly descriptionInput: Locator;
  readonly serverUrlInput: Locator;
  readonly submitButton: Locator;

  // Auth modal
  readonly authMethodSelect: Locator;
  readonly apiTokenInput: Locator;
  readonly oauthClientIdInput: Locator;
  readonly oauthClientSecretInput: Locator;
  readonly connectButton: Locator;

  // Server card + tools
  readonly refreshToolsButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.addServerButton = page.getByRole("button", {
      name: /Add MCP Server/i,
    });
    this.nameInput = page.locator("input#name");
    this.descriptionInput = page.locator("textarea#description");
    this.serverUrlInput = page.locator("input#server_url");
    this.submitButton = page.getByRole("button", { name: "Add Server" });

    this.authMethodSelect = page.getByTestId("mcp-auth-method-select");
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
    await this.page.goto("/admin/actions/mcp");
    await this.page.waitForURL("**/admin/actions/mcp**");
  }

  // ---------------------------------------------------------------------------
  // Add-server modal
  // ---------------------------------------------------------------------------

  async openAddServerModal(): Promise<void> {
    await this.addServerButton.click();
    await expect(this.nameInput).toBeVisible();
  }

  async fillServerDetails(details: {
    name: string;
    description?: string;
    url: string;
  }): Promise<void> {
    await this.nameInput.fill(details.name);
    if (details.description) {
      await this.descriptionInput.fill(details.description);
    }
    await this.serverUrlInput.fill(details.url);
  }

  /**
   * Submit the add-server modal, returning the created (bare) server id. The
   * auth-configuration modal opens automatically afterwards.
   */
  async submitAddServer(): Promise<number> {
    const responsePromise = this.page.waitForResponse(
      (resp) =>
        new URL(resp.url()).pathname === "/api/admin/mcp/server" &&
        resp.request().method() === "POST" &&
        resp.ok()
    );
    await this.submitButton.click();
    const response = await responsePromise;
    const created = (await response.json()) as { id?: number };
    expect(created.id).toBeTruthy();
    await expect(this.authMethodSelect).toBeVisible();
    return Number(created.id);
  }

  // ---------------------------------------------------------------------------
  // Auth modal
  // ---------------------------------------------------------------------------

  async selectAuthMethod(method: "OAuth" | "API Key"): Promise<void> {
    await this.authMethodSelect.click();
    await this.page.getByRole("option", { name: method }).click();
  }

  async selectApiKeyTab(which: "admin" | "per-user"): Promise<void> {
    const pattern =
      which === "admin" ? /Shared Key.*Admin/i : /Individual Key.*Per User/i;
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
    await expect(this.headerGroup.getByLabel("Key 1")).toHaveValue(
      "Authorization"
    );
    await expect(this.headerGroup.getByLabel("Value 1")).toHaveValue(
      "Bearer {api_key}"
    );
  }

  async addHeaderRow(): Promise<void> {
    await this.headerGroup
      .getByRole("button", { name: /Add Header Name and Header Value pair/i })
      .click();
  }

  async fillHeaderRow(
    index: number,
    name: string,
    value: string
  ): Promise<void> {
    const nameInput = this.headerGroup.getByLabel(`Key ${index}`);
    const valueInput = this.headerGroup.getByLabel(`Value ${index}`);
    await expect(nameInput).toBeVisible();
    await nameInput.fill(name);
    await valueInput.fill(value);
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
  // Server card + tool toggles
  // ---------------------------------------------------------------------------

  async expectServerCard(serverName: string): Promise<void> {
    await expect(
      this.page.getByText(serverName, { exact: false }).first()
    ).toBeVisible();
  }

  async refreshTools(): Promise<void> {
    await expect(this.refreshToolsButton).toBeVisible();
    await this.refreshToolsButton.click();
    await expect(this.page.getByText("No tools available")).not.toBeVisible();
  }

  cardToolToggle(toolName: string): Locator {
    return this.page.getByLabel(`tool-toggle-${toolName}`);
  }

  /**
   * Set every visible instance of a card tool toggle to the desired state.
   * (The same tool can render more than once on the page.)
   */
  async setCardToolEnabled(toolName: string, enabled: boolean): Promise<void> {
    const toggles = this.cardToolToggle(toolName);
    await expect(toggles.first()).toBeVisible();
    const count = await toggles.count();
    const desired = enabled ? "true" : "false";
    for (let i = 0; i < count; i++) {
      const toggle = toggles.nth(i);
      if ((await toggle.getAttribute("aria-checked")) !== desired) {
        await toggle.click();
        await expect(toggle).toHaveAttribute("aria-checked", desired);
      }
    }
  }
}
