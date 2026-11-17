import { type Page, type Locator, expect } from "@playwright/test";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";
import { AdminIntegrationDetailPage } from "@tests/e2e/pages/AdminIntegrationDetailPage";

/** An MCP server on the admin integration pages. */
export class AdminMcpServersPage {
  readonly page: Page;
  readonly integrations: AdminIntegrationsPage;
  readonly detail: AdminIntegrationDetailPage;

  readonly nameInput: Locator;
  readonly serverUrlInput: Locator;
  readonly refreshToolsButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.integrations = new AdminIntegrationsPage(page);
    this.detail = new AdminIntegrationDetailPage(page);
    this.nameInput = this.integrations.nameInput;
    this.serverUrlInput = this.integrations.serverUrlInput;
    this.refreshToolsButton = this.detail.refreshActionsButton;
  }

  async goto(): Promise<void> {
    await this.integrations.goto();
  }

  async openAddServerModal(): Promise<void> {
    await this.integrations.openAdd("MCP server");
    await expect(this.serverUrlInput).toBeVisible();
  }

  /** Adds an MCP server and returns its integration id. */
  async addServer(details: {
    name: string;
    url: string;
    owner?: "For me" | "For the organization";
  }): Promise<number> {
    await this.goto();
    await this.openAddServerModal();
    await this.integrations.fillMcpServer(details);
    if (details.owner) await this.integrations.chooseOwner(details.owner);
    return this.integrations.submit();
  }

  async expectServerDetail(serverName: string): Promise<void> {
    await expect(this.page).toHaveURL(/\/admin\/integrations\/\d+(?:\?.*)?$/);
    await this.detail.expectLoaded(serverName);
    await this.detail.openTab("Actions");
    await expect(this.refreshToolsButton).toBeEnabled();
  }

  async refreshTools(): Promise<void> {
    await expect(this.refreshToolsButton).toBeVisible();
    await this.detail.refreshActions();
  }
}
