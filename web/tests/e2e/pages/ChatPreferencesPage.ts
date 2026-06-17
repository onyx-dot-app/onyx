/**
 * Page Object Model for the admin "Chat Preferences" page
 * (/admin/configuration/chat-preferences).
 *
 * Covers attaching an MCP server's tools to the default agent, toggling
 * individual tools (with persistence), and editing the default system prompt.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class ChatPreferencesPage {
  readonly page: Page;
  readonly title: Locator;
  readonly modifyPromptButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.title = page.locator('[aria-label="admin-page-title"]');
    this.modifyPromptButton = page.getByText("Modify Prompt");
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  async goto(): Promise<void> {
    await this.page.goto("/admin/configuration/chat-preferences");
    await this.page.waitForURL("**/admin/configuration/chat-preferences**");
    await expect(this.title).toBeVisible();
  }

  private async scrollToBottom(): Promise<void> {
    await this.page
      .evaluate(() => window.scrollTo(0, document.body.scrollHeight))
      .catch(() => {});
  }

  // ---------------------------------------------------------------------------
  // Server card + tools
  // ---------------------------------------------------------------------------

  serverCard(serverName: string): Locator {
    return this.page
      .locator(".opal-card-expandable")
      .filter({ hasText: serverName })
      .first();
  }

  serverSwitch(serverName: string): Locator {
    return this.serverCard(serverName).getByRole("switch").first();
  }

  /** Turn the server-level switch on (enables all its tools) and await the save. */
  async enableServerTools(serverName: string): Promise<void> {
    await this.scrollToBottom();
    const card = this.serverCard(serverName);
    await expect(card).toBeVisible();
    await card.scrollIntoViewIfNeeded();

    const toggle = this.serverSwitch(serverName);
    await expect(toggle).toBeVisible();
    if ((await toggle.getAttribute("aria-checked")) !== "true") {
      await toggle.click();
      await this.expectToast("Tools updated");
    }
  }

  async expandServerCard(serverName: string): Promise<void> {
    await this.scrollToBottom();
    const card = this.serverCard(serverName);
    await expect(card).toBeVisible();
    await card.scrollIntoViewIfNeeded();

    // Scope the Expand control to this server's card so it can't toggle a
    // different expandable card on the page.
    const expandButton = card.getByRole("button", { name: "Expand" }).first();
    if (await expandButton.isVisible().catch(() => false)) {
      await expandButton.click();
    }
  }

  toolSwitch(toolName: string): Locator {
    return this.page
      .locator(".opal-card")
      .filter({ hasText: toolName })
      .first()
      .getByRole("switch")
      .first();
  }

  /** Toggle an individual tool switch and await the auto-save toast. */
  async toggleTool(toolName: string): Promise<void> {
    const toggle = this.toolSwitch(toolName);
    await expect(toggle).toBeVisible();
    await toggle.scrollIntoViewIfNeeded();
    // Force the click: the switch is actionable, but the card's expand
    // animation (a clipping/height-transition wrapper) can intercept the
    // hit-test on slower runners, leaving a plain click retrying until timeout.
    await toggle.click({ force: true });
    await this.expectToast("Tools updated");
  }

  // ---------------------------------------------------------------------------
  // System prompt modal
  // ---------------------------------------------------------------------------

  private get promptDialog(): Locator {
    return this.page.getByRole("dialog");
  }

  private get promptTextarea(): Locator {
    return this.promptDialog.getByPlaceholder("Enter your system prompt...");
  }

  async openModifyPrompt(): Promise<void> {
    await expect(this.modifyPromptButton).toBeVisible();
    await this.modifyPromptButton.click();
    await expect(this.promptDialog).toBeVisible();
  }

  async fillSystemPrompt(text: string): Promise<void> {
    await this.promptTextarea.fill(text);
  }

  async saveSystemPrompt(): Promise<void> {
    await this.promptDialog.getByRole("button", { name: "Save" }).click();
    await this.expectToast("System prompt updated");
    await expect(this.promptDialog).not.toBeVisible();
  }

  async cancelModifyPrompt(): Promise<void> {
    await this.promptDialog.getByRole("button", { name: "Cancel" }).click();
  }

  async expectSystemPromptValue(text: string): Promise<void> {
    await expect(this.promptTextarea).toHaveValue(text);
  }

  // ---------------------------------------------------------------------------
  // Misc
  // ---------------------------------------------------------------------------

  async expectToast(message: string | RegExp): Promise<void> {
    await expect(this.page.getByText(message).first()).toBeVisible();
  }
}
