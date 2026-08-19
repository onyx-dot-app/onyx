/**
 * Page Object Model for the admin "Chat Preferences" page
 * (/admin/configuration/chat-preferences).
 *
 * Covers attaching an MCP server's tools to the default agent, toggling
 * individual tools (with persistence), editing the default system prompt, and
 * the "Keep Chat History" retention control.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class ChatPreferencesPage {
  readonly page: Page;
  readonly title: Locator;
  readonly modifyPromptButton: Locator;
  readonly retentionField: Locator;

  constructor(page: Page) {
    this.page = page;
    this.title = page.locator('[aria-label="admin-page-title"]');
    this.modifyPromptButton = page.getByText("Modify Prompt");
    this.retentionField = page
      .locator("label")
      .filter({ hasText: "Keep Chat History" });
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
  // Chat retention ("Keep Chat History")
  // ---------------------------------------------------------------------------

  get retentionTrigger(): Locator {
    return this.retentionField.locator('[role="combobox"]');
  }

  /** The "In days" input shown once "Custom Retention" is selected. */
  get retentionCustomInput(): Locator {
    return this.retentionField.getByPlaceholder("In days");
  }

  /** First icon button in the custom input restores the default (Forever). */
  get retentionRestoreDefaultButton(): Locator {
    return this.retentionField
      .locator(".opal-input")
      .getByRole("button")
      .first();
  }

  /** Second icon button in the custom input reopens the preset dropdown. */
  get retentionMoreButton(): Locator {
    return this.retentionField
      .locator(".opal-input")
      .getByRole("button")
      .nth(1);
  }

  get reduceRetentionModal(): Locator {
    return this.page.getByText("Reduce chat retention?");
  }

  retentionOption(label: string): Locator {
    return this.page.getByRole("option", { name: label, exact: true });
  }

  /** Expand the "Advanced Options" collapsible so the retention control shows. */
  async expandAdvancedOptions(): Promise<void> {
    const header = this.page.getByText("Advanced Options", { exact: true });
    await expect(header).toBeVisible();
    if (
      await this.retentionField
        .first()
        .isVisible()
        .catch(() => false)
    ) {
      return;
    }
    await header.scrollIntoViewIfNeeded();
    await header.click();
    await expect(this.retentionField.first()).toBeVisible();
  }

  /** Navigate to the page and reveal the retention control. */
  async gotoAdvancedOptions(): Promise<void> {
    await this.goto();
    await this.page.waitForLoadState("networkidle");
    await this.expandAdvancedOptions();
  }

  /** Reload and re-reveal the retention control (Advanced Options recollapses). */
  async reloadAdvancedOptions(): Promise<void> {
    await this.page.reload();
    await this.page.waitForLoadState("networkidle");
    await this.expandAdvancedOptions();
  }

  async openRetentionDropdown(): Promise<void> {
    await this.retentionTrigger.click();
  }

  async selectRetentionPreset(label: string): Promise<void> {
    await this.openRetentionDropdown();
    await this.retentionOption(label).click();
  }

  /** Choose "Custom Retention" and wait for the days input to appear. */
  async chooseCustomRetention(): Promise<void> {
    await this.openRetentionDropdown();
    await this.retentionOption("Custom Retention").click();
    await expect(this.retentionCustomInput).toBeVisible();
  }

  async confirmRetentionReduction(): Promise<void> {
    await expect(this.reduceRetentionModal).toBeVisible();
    await this.page.getByRole("button", { name: "Reduce retention" }).click();
    await this.expectToast("Settings updated");
  }

  async cancelRetentionReduction(): Promise<void> {
    // No inputs live inside the modal, so Escape dismisses it immediately.
    await this.page.keyboard.press("Escape");
    await expect(this.reduceRetentionModal).toHaveCount(0);
  }

  /**
   * Enter a custom retention value coming from Forever/a larger value. This
   * shortens the retention window, so it triggers (and confirms) the reduction
   * prompt.
   */
  async setCustomRetention(days: string): Promise<void> {
    await this.chooseCustomRetention();
    await this.retentionCustomInput.fill(days);
    await this.retentionCustomInput.blur();
    await this.confirmRetentionReduction();
  }

  async restoreRetentionDefault(): Promise<void> {
    await this.retentionRestoreDefaultButton.click();
    await this.expectToast("Settings updated");
  }

  /** Best-effort reset so shared state is left at the safe "Forever" default. */
  async resetRetentionToForever(): Promise<void> {
    await this.gotoAdvancedOptions();
    if (await this.retentionCustomInput.isVisible().catch(() => false)) {
      await this.retentionRestoreDefaultButton.click();
      await this.expectToast("Settings updated").catch(() => {});
      return;
    }
    if (
      ((await this.retentionTrigger.textContent()) ?? "").includes("Forever")
    ) {
      return;
    }
    await this.selectRetentionPreset("Forever");
    await this.expectToast("Settings updated");
  }

  // ---------------------------------------------------------------------------
  // Misc
  // ---------------------------------------------------------------------------

  async expectToast(message: string | RegExp): Promise<void> {
    await expect(this.page.getByText(message).first()).toBeVisible();
  }
}
