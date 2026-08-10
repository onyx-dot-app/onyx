/**
 * Page Object Model for the chat "Actions" popover and its MCP credentials
 * modal.
 *
 * The popover (opened from the chat input's action-management toggle) lists the
 * agent's MCP servers and lets the user drill into a server to enable/disable
 * individual tools, re-authenticate, or enter per-user credentials. This class
 * encapsulates every locator and interaction those flows need so specs stay
 * declarative.
 */

import { type Page, type Locator, expect } from "@playwright/test";

const POPOVER = '[data-testid="tool-options"]';
const LINE_ITEM = ".group\\/LineItem";

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * The per-user credentials dialog (Enter / Manage Credentials) that the popover
 * opens for template-based MCP servers. Exposed as `actionsPopover.credentialsModal`.
 */
export class McpCredentialsModal {
  readonly page: Page;
  readonly dialog: Locator;
  readonly apiKeyField: Locator;
  readonly usernameField: Locator;
  readonly saveButton: Locator;
  readonly updateButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.dialog = page.getByRole("dialog");
    this.apiKeyField = this.dialog.locator("input#api_key");
    this.usernameField = this.dialog.locator("input#username");
    this.saveButton = this.dialog.getByRole("button", {
      name: /Save Credentials/i,
    });
    this.updateButton = this.dialog.getByRole("button", {
      name: /Update Credentials/i,
    });
  }

  async expectOpen(titlePattern: RegExp): Promise<void> {
    await expect(this.dialog).toBeVisible();
    await expect(this.dialog.getByText(titlePattern)).toBeVisible();
  }

  async expectFieldsVisible(): Promise<void> {
    await expect(this.apiKeyField).toBeVisible();
    await expect(this.usernameField).toBeVisible();
  }

  async fillApiKey(value: string): Promise<void> {
    await this.apiKeyField.fill(value);
  }

  async fillUsername(value: string): Promise<void> {
    await this.usernameField.fill(value);
  }

  /**
   * Submit the modal via the Save button and assert the credentials POST
   * succeeds, then wait for the dialog to close.
   */
  async save(): Promise<void> {
    const responsePromise = this.page.waitForResponse(
      (resp) =>
        new URL(resp.url()).pathname === "/api/mcp/user-credentials" &&
        resp.request().method() === "POST"
    );
    await this.saveButton.click();
    const response = await responsePromise;
    expect(response.ok()).toBeTruthy();
    await expect(this.dialog).not.toBeVisible();
  }
}

export class ActionsPopover {
  readonly page: Page;
  readonly toggle: Locator;
  readonly popover: Locator;
  readonly serverRows: Locator;
  readonly toolSwitches: Locator;
  readonly credentialsModal: McpCredentialsModal;

  constructor(page: Page) {
    this.page = page;
    this.toggle = page.getByTestId("action-management-toggle");
    this.popover = page.locator(POPOVER);
    this.serverRows = this.popover.locator("[data-mcp-server-name]");
    this.toolSwitches = this.popover.locator('[role="switch"]');
    this.credentialsModal = new McpCredentialsModal(page);
  }

  // ---------------------------------------------------------------------------
  // Open / close / navigation
  // ---------------------------------------------------------------------------

  private get backButton(): Locator {
    return this.popover.getByRole("button", { name: /Back/i }).first();
  }

  async open(): Promise<void> {
    if (!(await this.popover.isVisible().catch(() => false))) {
      await this.toggle.click();
      await expect(this.popover).toBeVisible();
    }
    await this.ensurePrimaryView();
  }

  /** If drilled into a server's tool list, step back out to the server list. */
  private async ensurePrimaryView(): Promise<void> {
    if (!(await this.popover.isVisible().catch(() => false))) {
      return;
    }
    if ((await this.serverRows.count()) > 0) {
      return;
    }
    if ((await this.backButton.count()) > 0) {
      await this.backButton.click().catch(() => {});
    }
  }

  async close(): Promise<void> {
    if (this.page.isClosed()) {
      return;
    }
    if (await this.backButton.count().catch(() => 0)) {
      await this.backButton.click().catch(() => {});
    }
    await this.page.keyboard.press("Escape").catch(() => {});
  }

  // ---------------------------------------------------------------------------
  // Server rows
  // ---------------------------------------------------------------------------

  serverRow(serverName: string): Locator {
    return this.popover
      .locator(LINE_ITEM)
      .filter({ hasText: new RegExp(escapeRegex(serverName)) })
      .first();
  }

  async expectServerVisible(serverName: string): Promise<void> {
    await this.open();
    await expect(this.serverRow(serverName)).toBeVisible();
  }

  /**
   * Ensure the server row is visible, retrying once by re-selecting the agent
   * (the popover occasionally loses agent context after an OAuth round-trip).
   */
  async ensureServerVisible(
    serverName: string,
    options?: { agentId?: number }
  ): Promise<void> {
    for (let attempt = 0; attempt < 2; attempt++) {
      await this.open();
      if (
        await this.serverRow(serverName)
          .isVisible()
          .catch(() => false)
      ) {
        await expect(this.serverRow(serverName)).toBeVisible();
        await this.page.keyboard.press("Escape").catch(() => {});
        return;
      }
      await this.page.keyboard.press("Escape").catch(() => {});
      if (attempt === 0 && options?.agentId) {
        await this.restoreAgentContext(options.agentId);
      }
    }
    throw new Error(`Server ${serverName} not visible in actions popover`);
  }

  /**
   * Click a server row without asserting what follows. For an authenticated
   * server this drills into the tool list; for an unauthenticated per-user
   * server it opens the credentials modal.
   */
  async clickServer(serverName: string): Promise<void> {
    await this.open();
    const row = this.serverRow(serverName);
    await expect(row).toBeVisible();
    await row.click({ force: true });
  }

  /** Drill into a server to reveal its individual tools. */
  async openServer(serverName: string): Promise<void> {
    await this.open();
    // The popover fetches its server list when it opens, so the row can mount a
    // beat after the popover is visible and a plain click can land before the
    // row is interactive. Retry a force-click until the tool-list view actually
    // appears. (Callers must ensure the server is authenticated first;
    // clicking an unauthenticated server starts OAuth instead of drilling in.)
    const toolListView = this.popover
      .getByText(/(Enable|Disable) All/i)
      .first();
    await expect(async () => {
      if (await toolListView.isVisible().catch(() => false)) {
        return;
      }
      const row = this.serverRow(serverName);
      await expect(row).toBeVisible({ timeout: 3000 });
      await row.click({ force: true, timeout: 3000 });
      await expect(toolListView).toBeVisible({ timeout: 3000 });
    }).toPass({ timeout: 60000, intervals: [300, 700, 1500] });
  }

  async expectToolListView(): Promise<void> {
    await expect(
      this.popover.getByText(/(Enable|Disable) All/i).first()
    ).toBeVisible();
  }

  /** Non-throwing: whether the drilled-in tool-list view appears within `timeoutMs`. */
  async toolListVisible(timeoutMs = 3000): Promise<boolean> {
    return this.popover
      .getByText(/(Enable|Disable) All/i)
      .first()
      .waitFor({ state: "visible", timeout: timeoutMs })
      .then(() => true)
      .catch(() => false);
  }

  // ---------------------------------------------------------------------------
  // Tool rows
  // ---------------------------------------------------------------------------

  searchInput(): Locator {
    return this.popover.getByPlaceholder(/Search .* tools/i).first();
  }

  async searchTool(toolName: string): Promise<void> {
    await this.searchInput().fill(toolName);
  }

  toolToggle(toolName: string): Locator {
    return this.popover.getByLabel(`Toggle ${toolName}`).first();
  }

  toolRow(toolName: string): Locator {
    return this.popover
      .locator(LINE_ITEM)
      .filter({ hasText: new RegExp(`^${escapeRegex(toolName)}`) })
      .first();
  }

  private async isToolChecked(toolName: string): Promise<boolean> {
    const toggle = this.toolToggle(toolName);
    const dataState = await toggle.getAttribute("data-state");
    if (typeof dataState === "string") {
      return dataState === "checked";
    }
    return (await toggle.getAttribute("aria-checked")) === "true";
  }

  async setToolEnabled(toolName: string, enabled: boolean): Promise<void> {
    const toggle = this.toolToggle(toolName);
    await expect(toggle).toBeVisible();
    // Retry the toggle click until the state sticks: the popover can re-render
    // (auth-status polling) and swallow a single click before it registers.
    await expect(async () => {
      if ((await this.isToolChecked(toolName)) !== enabled) {
        await toggle.click({ force: true, timeout: 3000 });
      }
      expect(await this.isToolChecked(toolName)).toBe(enabled);
    }).toPass({ timeout: 30000, intervals: [300, 700, 1500] });
  }

  async enableTool(toolName: string): Promise<void> {
    await this.setToolEnabled(toolName, true);
  }

  async disableTool(toolName: string): Promise<void> {
    await this.setToolEnabled(toolName, false);
  }

  async enableAll(): Promise<void> {
    await this.popover
      .getByText(/Enable All/i)
      .first()
      .click();
  }

  async disableAll(): Promise<void> {
    await this.popover
      .getByText(/Disable All/i)
      .first()
      .click();
  }

  // ---------------------------------------------------------------------------
  // Composite helpers
  // ---------------------------------------------------------------------------

  /** Open the popover, drill into the server, and confirm a tool row is shown. */
  async expectToolRowVisible(
    serverName: string,
    toolName: string
  ): Promise<void> {
    await this.openServer(serverName);
    await expect(this.toolToggle(toolName)).toBeVisible();
    await this.close();
  }

  // ---------------------------------------------------------------------------
  // Re-authentication (OAuth + per-user)
  // ---------------------------------------------------------------------------

  reauthRow(): Locator {
    return this.popover
      .locator(LINE_ITEM)
      .filter({ hasText: /Re-Authenticate/i })
      .first();
  }

  async clickReauthRow(): Promise<void> {
    const row = this.reauthRow();
    await expect(row).toBeVisible();
    await row.click({ force: true });
  }

  /**
   * Click a server row and report whether doing so navigated away (OAuth flows
   * leave the app immediately) or merely drilled into the in-popover tool list.
   * Used by the OAuth re-auth orchestration.
   */
  async clickServerRowDetectingNavigation(
    serverName: string,
    urlChangeWaitMs = 5000
  ): Promise<"navigated" | "drilled"> {
    await this.open();
    const row = this.serverRow(serverName);
    await expect(row).toBeVisible();

    const startUrl = this.page.url();
    const navigated = this.page
      .waitForURL((url) => url.toString() !== startUrl, {
        timeout: urlChangeWaitMs,
      })
      .then(() => true)
      .catch(() => false);

    await row.click({ force: true });
    if (await navigated) {
      return "navigated";
    }
    return "drilled";
  }

  // ---------------------------------------------------------------------------
  // Agent context restore
  // ---------------------------------------------------------------------------

  private async restoreAgentContext(agentId: number): Promise<void> {
    await this.page.goto("/app", { waitUntil: "domcontentloaded" });
    await this.page.waitForLoadState("networkidle").catch(() => {});

    const link = this.page.locator(`a[href*="agentId=${agentId}"]`).first();
    if ((await link.count()) > 0) {
      await link.click();
    } else {
      await this.page.goto(`/app?agentId=${agentId}`, {
        waitUntil: "domcontentloaded",
      });
    }
    await this.page.waitForLoadState("networkidle").catch(() => {});
  }
}
