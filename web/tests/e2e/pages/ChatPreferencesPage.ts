/**
 * Page Object Model for the admin "Chat Preferences" page
 * (/admin/chat-preferences).
 *
 * Covers editing the default system prompt and the "Keep Chat History"
 * retention control.
 */

import { type Page, type Locator, expect } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

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
    await this.page.goto(ADMIN_ROUTES.CHAT_PREFERENCES.path);
    await this.page.waitForURL(`**${ADMIN_ROUTES.CHAT_PREFERENCES.path}**`);
    await expect(this.title).toBeVisible();
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
    // The trigger is a read-only input: its text is its value.
    if ((await this.retentionTrigger.inputValue()).includes("Forever")) {
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
