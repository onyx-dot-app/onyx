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
  readonly onboardingHeader: Locator;
  readonly nameStep: Locator;
  readonly noAgentModal: Locator;

  constructor(page: Page) {
    this.page = page;
    this.namePrompt = page.locator('[aria-label="non-admin-name-prompt"]');
    this.confirmation = page.locator('[aria-label="non-admin-confirmation"]');
    this.chatInput = page.locator("#onyx-chat-input");
    this.onboardingHeader = page.locator('[data-label="onboarding-header"]');
    this.nameStep = page.locator('[aria-label="onboarding-name-step"]');
    this.noAgentModal = page.getByText("No Agent Available");
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

  /** Open a chat session and wait for the chat input. */
  async gotoChat(chatSessionId: string): Promise<void> {
    await this.page.goto(`/app?chatId=${chatSessionId}`);
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

  /** Open /app with the agents request failing and the user's `/api/me`
   *  response held until the no-agent modal shows. The user then loads under
   *  the modal, and a later retry of the agents request mounts the page. */
  async gotoAfterAgentsFail(): Promise<void> {
    let failing = true;
    let releaseUser = () => {};
    const userHeld = new Promise<void>((resolve) => {
      releaseUser = resolve;
    });
    await this.page.route("**/api/persona", (route) =>
      failing ? route.fulfill({ status: 500, body: "{}" }) : route.continue()
    );
    await this.page.route("**/api/me", async (route) => {
      await userHeld;
      await route.continue();
    });
    await this.page.goto("/app");
    await expect(this.noAgentModal).toBeVisible({ timeout: 15000 });
    const userLoaded = this.page.waitForResponse("**/api/me");
    releaseUser();
    await userLoaded;
    failing = false;
    await expect(this.chatInput).toBeVisible({ timeout: 30000 });
  }

  /** The chat input's top edge, or NaN while it has no box. */
  async chatInputTop(): Promise<number> {
    return (await this.chatInput.boundingBox())?.y ?? Number.NaN;
  }

  /** The chat input's top edge once two readings in a row match. */
  async settledChatInputTop(): Promise<number> {
    let top = Number.NaN;
    await expect
      .poll(async () => {
        const next = await this.chatInputTop();
        const settled = next === top;
        top = next;
        return settled;
      })
      .toBe(true);
    return top;
  }

  /** Reload /app and wait for the chat input. */
  async reload(): Promise<void> {
    await this.page.reload();
    await expect(this.chatInput).toBeVisible({ timeout: 15000 });
  }
}
