/**
 * Page Object Model for the admin "Chat Preferences" page
 * (/admin/chat-preferences).
 *
 * Covers editing the default system prompt.
 */

import {
  type Page,
  type Locator,
  type Response,
  expect,
} from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

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
    const saved = this.waitForPatch("/api/admin/default-assistant");
    await this.promptDialog.getByRole("button", { name: "Save" }).click();
    expect((await saved).ok()).toBeTruthy();
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

  /** Resolves with the next PATCH to `pathname`; start it before the action. */
  waitForPatch(pathname: string): Promise<Response> {
    return this.page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === pathname &&
        response.request().method() === "PATCH"
    );
  }

  async expectToast(message: string | RegExp): Promise<void> {
    await expect(this.page.getByText(message).first()).toBeVisible();
  }
}
