/** Page Object Model for creating and editing agents. */

import { type Page, type Locator, expect } from "@playwright/test";

export class AgentEditorPage {
  readonly page: Page;
  readonly nameInput: Locator;
  readonly instructionsInput: Locator;
  readonly descriptionInput: Locator;
  readonly createButton: Locator;
  readonly defaultModelTrigger: Locator;
  readonly defaultModelListbox: Locator;

  constructor(page: Page) {
    this.page = page;
    this.nameInput = page.locator('input[name="name"]');
    this.instructionsInput = page.locator('textarea[name="instructions"]');
    this.descriptionInput = page.locator('textarea[name="description"]');
    this.createButton = page.getByRole("button", { name: "Create" });
    // The Default Model picker is a select inside its labelled row; its
    // list is portalled, so the listbox is found from the page.
    this.defaultModelTrigger = page
      .locator("label")
      .filter({ hasText: "Default Model" })
      .first()
      .getByRole("combobox", { name: "Select model" });
    this.defaultModelListbox = page.getByRole("listbox", {
      name: "Select model",
    });
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  async goto(): Promise<void> {
    await this.page.goto("/app/agents/create");
    await this.page.waitForURL("**/app/agents/create**");
    await expect(this.nameInput).toBeVisible();
  }

  async gotoEdit(agentId: number): Promise<void> {
    const providerResponse = this.page.waitForResponse(
      (response) =>
        response.url().includes(`/api/llm/persona/${agentId}/providers`) &&
        response.ok()
    );
    await this.page.goto(`/app/agents/edit/${agentId}`);
    await providerResponse;
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

  async expectDefaultModelOptions(expected: {
    visible: Array<string | RegExp>;
    hidden?: Array<string | RegExp>;
  }): Promise<void> {
    await this.defaultModelTrigger.scrollIntoViewIfNeeded();
    await this.defaultModelTrigger.click();
    await expect(this.defaultModelListbox).toBeVisible();

    // Providers are foldable groups; a folded group still shows its title.
    for (const option of expected.visible) {
      await expect(this.defaultModelListbox).toContainText(option);
    }
    for (const option of expected.hidden ?? []) {
      await expect(this.defaultModelListbox).not.toContainText(option);
    }

    await this.page.keyboard.press("Escape");
    await expect(this.defaultModelListbox).toBeHidden();
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
