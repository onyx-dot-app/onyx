/** Page Object Model for creating and editing agents. */

import { type Page, type Locator, expect } from "@playwright/test";

export type ActionSettingLabel =
  | "Use the agent default"
  | "Use the integration setting"
  | "Allow"
  | "Ask"
  | "Blocked";

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

  actionSetting(actionName: string): Locator {
    return this.page.getByRole("combobox", {
      name: `Setting for ${actionName}`,
    });
  }

  async addIntegration(integrationName: string): Promise<void> {
    const add = this.page.getByRole("combobox", { name: "Add an integration" });
    await add.scrollIntoViewIfNeeded();
    await add.click();
    await this.page.getByRole("option", { name: integrationName }).click();
    await expect(
      this.page.getByRole("button", { name: `Remove ${integrationName}` })
    ).toBeVisible();
  }

  async setActionSetting(
    actionName: string,
    setting: ActionSettingLabel
  ): Promise<void> {
    const select = this.actionSetting(actionName);
    await select.scrollIntoViewIfNeeded();
    await select.click();
    await this.page.getByRole("option", { name: setting, exact: true }).click();
    await expect(select).toHaveValue(setting);
  }

  async expectActionSetting(
    actionName: string,
    setting: ActionSettingLabel,
    applies: string
  ): Promise<void> {
    const select = this.actionSetting(actionName);
    await select.scrollIntoViewIfNeeded();
    await expect(select).toHaveValue(setting);
    await expect(this.page.getByText(applies, { exact: true })).toBeVisible();
  }

  /** Opens the setting of an action and checks that a choice is not offered. */
  async expectSettingNotOffered(
    actionName: string,
    setting: ActionSettingLabel
  ): Promise<void> {
    const select = this.actionSetting(actionName);
    await select.scrollIntoViewIfNeeded();
    await select.click();
    await expect(
      this.page.getByRole("option", { name: "Ask", exact: true })
    ).toBeVisible();
    await expect(
      this.page.getByRole("option", { name: setting, exact: true })
    ).toHaveCount(0);
    await this.page.keyboard.press("Escape");
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
