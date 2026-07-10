/**
 * Page Object Model for the craft welcome page (/craft/v1) and its provider
 * onboarding surfaces: the first-visit intro modal, the inline LLM-provider
 * setup card shown to admins without a build-mode provider, and the locked
 * notice shown to non-admins. Encapsulates every locator these flows need so
 * specs stay declarative.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class CraftWelcomePage {
  readonly page: Page;
  readonly introHeading: Locator;
  readonly introGetStartedButton: Locator;
  readonly llmSetup: Locator;
  readonly llmSetupToggle: Locator;
  readonly lockedState: Locator;
  readonly messageInput: Locator;
  readonly providerModal: Locator;

  constructor(page: Page) {
    this.page = page;
    this.introHeading = page.getByText("What is Onyx Craft?");
    this.introGetStartedButton = page.getByRole("button", {
      name: "Get Started!",
    });
    this.llmSetup = page.locator('[aria-label="craft-llm-setup"]');
    this.llmSetupToggle = this.llmSetup.getByRole("switch");
    this.lockedState = page.locator('[aria-label="craft-llm-locked"]');
    this.messageInput = page.locator('[aria-label="Message input"]');
    this.providerModal = page.getByRole("dialog");
  }

  async goto(): Promise<void> {
    await this.page.goto("/craft/v1");
  }

  /** Dismisses the first-visit intro modal. */
  async dismissIntro(): Promise<void> {
    await expect(this.introHeading).toBeVisible({ timeout: 15000 });
    await this.introGetStartedButton.click();
    await expect(this.introHeading).not.toBeVisible();
  }

  providerCard(name: string): Locator {
    return this.llmSetup.getByText(name, { exact: true });
  }

  /** Flips the "Recommended providers only" switch on the setup card. */
  async toggleRecommendedOnly(): Promise<void> {
    await this.llmSetupToggle.click();
  }

  async openProviderSetup(name: string): Promise<void> {
    await this.providerCard(name).click();
    await expect(this.providerModal.getByText(`Set up ${name}`)).toBeVisible({
      timeout: 10000,
    });
  }

  async expectInputDisabled(): Promise<void> {
    await expect(this.messageInput).toHaveAttribute("aria-disabled", "true");
  }

  async expectInputEnabled(): Promise<void> {
    await expect(this.messageInput).toBeVisible({ timeout: 15000 });
    await expect(this.messageInput).toHaveAttribute("aria-disabled", "false");
  }
}
