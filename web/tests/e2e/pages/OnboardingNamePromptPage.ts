/**
 * Page Object Model for the onboarding name prompt that a user without a
 * name sees above the chat input on /app.
 */

import { type Page, type Locator, expect } from "@playwright/test";
import type { UserPersonalization } from "@/lib/types";

export class OnboardingNamePromptPage {
  readonly page: Page;
  readonly namePrompt: Locator;
  readonly confirmation: Locator;
  readonly chatInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.namePrompt = page.locator('[aria-label="non-admin-name-prompt"]');
    this.confirmation = page.locator('[aria-label="non-admin-confirmation"]');
    this.chatInput = page.locator("#onyx-chat-input");
  }

  /** The signed-in user's saved personalization, read from `/api/me`. */
  async fetchPersonalization(): Promise<UserPersonalization> {
    const response = await this.page.request.get("/api/me");
    expect(response.ok()).toBe(true);
    const me = (await response.json()) as {
      personalization: UserPersonalization;
    };
    return me.personalization;
  }

  /** Open /app, or the given chat session, and wait for the chat input. */
  async goto(chatSessionId?: string): Promise<void> {
    await this.page.goto(
      chatSessionId ? `/app?chatId=${chatSessionId}` : "/app"
    );
    await expect(this.chatInput).toBeVisible({ timeout: 15000 });
  }

  /** Open /app and hold the user's `/api/me` response until the chat input
   *  shows, so the page renders before it knows the user. */
  async gotoBeforeUserLoads(): Promise<void> {
    let release = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await this.page.route("**/api/me", async (route) => {
      await held;
      await route.continue();
    });
    await this.page.goto("/app");
    await expect(this.chatInput).toBeVisible({ timeout: 15000 });
    await expect(this.namePrompt).toBeHidden();
    release();
  }

  /** The chat input's top edge, or NaN while it has no box. */
  async chatInputTop(): Promise<number> {
    return (await this.chatInput.boundingBox())?.y ?? Number.NaN;
  }

  /** Reload /app and wait for the chat input. */
  async reload(): Promise<void> {
    await this.page.reload();
    await expect(this.chatInput).toBeVisible({ timeout: 15000 });
  }
}
