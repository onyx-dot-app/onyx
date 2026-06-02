/**
 * Page Object Model for the agent editor (/app/agents/create).
 *
 * Encapsulates the MCP-related parts of agent creation: filling the basics and
 * enabling an MCP server + its tools. Most specs create agents via the API
 * client; this POM is for the tests that specifically exercise the editor UI.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class AgentEditorPage {
  readonly page: Page;
  readonly nameInput: Locator;
  readonly instructionsInput: Locator;
  readonly descriptionInput: Locator;
  readonly createButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.nameInput = page.locator('input[name="name"]');
    this.instructionsInput = page.locator('textarea[name="instructions"]');
    this.descriptionInput = page.locator('textarea[name="description"]');
    this.createButton = page.getByRole("button", { name: "Create" });
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  async goto(): Promise<void> {
    await this.page.goto("/app/agents/create");
    await this.page.waitForURL("**/app/agents/create**");
    await expect(this.nameInput).toBeVisible();
  }

  /** Navigate from the chat sidebar (the path a basic user takes). */
  async openFromSidebar(): Promise<void> {
    await this.page.getByTestId("AppSidebar/more-agents").click();
    await this.page.waitForURL("**/app/agents");
    await this.page.getByLabel("AgentsPage/new-agent-button").click();
    await this.page.waitForURL("**/app/agents/create");
    await expect(this.nameInput).toBeVisible();
  }

  // ---------------------------------------------------------------------------
  // Form
  // ---------------------------------------------------------------------------

  async fill(details: {
    name: string;
    description?: string;
    instructions?: string;
  }): Promise<void> {
    await this.nameInput.fill(details.name);
    if (details.description) {
      await this.descriptionInput.fill(details.description);
    }
    if (details.instructions) {
      await this.instructionsInput.fill(details.instructions);
    }
  }

  mcpServerSwitch(serverId: number): Locator {
    return this.page.locator(
      `button[role="switch"][name="mcp_server_${serverId}.enabled"]`
    );
  }

  firstMcpToolSwitch(serverId: number): Locator {
    return this.page
      .locator(`button[role="switch"][name^="mcp_server_${serverId}.tool_"]`)
      .first();
  }

  async enableMcpServer(serverId: number): Promise<void> {
    const toggle = this.mcpServerSwitch(serverId);
    await toggle.scrollIntoViewIfNeeded();
    if ((await toggle.getAttribute("aria-checked")) !== "true") {
      await toggle.click();
    }
    await expect(toggle).toHaveAttribute("aria-checked", "true");
  }

  async enableFirstMcpTool(serverId: number): Promise<void> {
    const toggle = this.firstMcpToolSwitch(serverId);
    await expect(toggle).toBeVisible();
    if ((await toggle.getAttribute("aria-checked")) !== "true") {
      await toggle.click();
    }
    await expect(toggle).toHaveAttribute("aria-checked", "true");
  }

  /** Submit the form and return the new agent's id (from the resulting URL). */
  async create(): Promise<number> {
    await this.createButton.click();
    await this.page.waitForURL(/\/app\?agentId=\d+/);
    const match = this.page.url().match(/agentId=(\d+)/);
    expect(match).toBeTruthy();
    return Number(match![1]);
  }
}
