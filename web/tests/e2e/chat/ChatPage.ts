/**
 * Page Object Model for the main chat page (/app).
 *
 * Encapsulates locators and interactions shared across chat specs so that
 * individual tests remain declarative.
 */

import { type Page, type Locator, expect } from "@playwright/test";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";
import { InputBar } from "@tests/e2e/chat/InputBar";

export class ChatPage {
  readonly page: Page;
  readonly inputBar: InputBar;

  // Layout containers
  readonly container: Locator;
  readonly scrollContainer: Locator;

  // Message collections
  readonly humanMessages: Locator;
  readonly aiMessages: Locator;
  readonly usageLimitBanner: Locator;

  // Model picker: the "Add Model" button, then one pill per selected model
  readonly modelSelector: Locator;
  /** A pill opens its switch list, where a row replaces that model. */
  readonly modelPills: Locator;
  readonly modelPopover: Locator;
  readonly modelSearchInput: Locator;
  /** Rows of the open list, each "selected" or "empty". */
  readonly modelOptions: Locator;
  readonly selectedModelOptions: Locator;
  readonly unselectedModelOptions: Locator;

  constructor(page: Page) {
    this.page = page;
    this.inputBar = new InputBar(page);
    this.container = page.locator("[data-main-container]");
    this.scrollContainer = page.getByTestId("chat-scroll-container");
    this.humanMessages = page.locator("#onyx-human-message");
    this.aiMessages = page.getByTestId("onyx-ai-message");
    this.usageLimitBanner = page.getByText(/you've reached the usage budget/i);
    this.modelSelector = page.getByTestId("model-selector");
    this.modelPills = this.modelSelector.locator(
      "button:not([aria-label='Add Model'])"
    );
    this.modelPopover = page.getByRole("dialog");
    this.modelSearchInput =
      this.modelPopover.getByPlaceholder("Search models...");
    this.modelOptions = this.modelPopover.locator("[data-interactive-state]");
    this.selectedModelOptions = this.modelPopover.locator(
      '[data-interactive-state="selected"]'
    );
    this.unselectedModelOptions = this.modelPopover.locator(
      '[data-interactive-state="empty"]'
    );
  }

  humanMessage(index = 0): Locator {
    return this.humanMessages.nth(index);
  }

  aiMessage(index = 0): Locator {
    return this.aiMessages.nth(index);
  }

  async goto(): Promise<void> {
    await this.page.goto("/app");
    await this.page.waitForLoadState("networkidle");
    await this.inputBar.textbox.waitFor({ state: "visible", timeout: 15000 });
  }

  async reload(): Promise<void> {
    await this.page.reload();
    await this.page.waitForLoadState("networkidle");
    await this.inputBar.textbox.waitFor({ state: "visible", timeout: 15000 });
  }

  async scrollTo(position: "top" | "bottom"): Promise<void> {
    await this.scrollContainer.evaluate(async (el, pos) => {
      el.scrollTo({ top: pos === "top" ? 0 : el.scrollHeight });
      await new Promise<void>((r) => requestAnimationFrame(() => r()));
    }, position);
  }

  async screenshotContainer(name: string): Promise<void> {
    await expect(this.container).toBeVisible();
    if ((await this.scrollContainer.count()) > 0) {
      await this.scrollTo("bottom");
    }
    await expectElementScreenshot(this.container, { name });
  }

  /**
   * Captures two screenshots of the chat container for long-content tests:
   * one scrolled to the top and one scrolled to the bottom. Ensures
   * consistent scroll positions regardless of whether the page was just
   * navigated to (top) or just finished streaming (bottom).
   */
  async screenshotContainerTopAndBottom(name: string): Promise<void> {
    await expect(this.container).toBeVisible();

    await this.scrollTo("top");
    await expectElementScreenshot(this.container, { name: `${name}-top` });

    await this.scrollTo("bottom");
    await expectElementScreenshot(this.container, { name: `${name}-bottom` });
  }

  // ---------------------------------------------------------------------------
  // Model picker
  // ---------------------------------------------------------------------------

  async expectModelPill(modelName: string, index = 0): Promise<void> {
    await expect(this.modelPills.nth(index)).toContainText(modelName);
  }

  async expectModelPillNot(modelText: string, index = 0): Promise<void> {
    await expect(this.modelPills.nth(index)).not.toHaveText(modelText);
  }

  /** Waits for the pill to render a name before reading it. */
  async readModelPillText(index = 0): Promise<string> {
    const pill = this.modelPills.nth(index);
    await expect(pill).toHaveText(/\S/);
    return (await pill.innerText()).trim();
  }

  /** Opens the first pill's switch list, filtered by `search` when given, and returns the popover. */
  async openModelList(search?: string): Promise<Locator> {
    await this.modelPills.first().click();
    await expect(this.modelSearchInput).toBeVisible({ timeout: 10000 });
    if (search !== undefined) await this.modelSearchInput.fill(search);
    return this.modelPopover;
  }

  modelOption(modelName: string): Locator {
    return this.modelOptions.filter({ hasText: modelName });
  }

  async closeModelPicker(): Promise<void> {
    await this.page.keyboard.press("Escape");
    await expect(this.modelPopover).toBeHidden();
  }

  /** Picks a row of the open list, which closes it, waits for the first pill to show the row's model and returns that name. */
  async chooseModelOption(option: Locator): Promise<string> {
    // A row's first line is its model's display name, the text its pill shows.
    const modelName = (await option.innerText()).split("\n")[0]?.trim() ?? "";
    await option.click();
    await expect(this.modelPopover).toBeHidden();
    await this.expectModelPill(modelName);
    return modelName;
  }

  /** Replaces the first pill's model through its switch list. */
  async switchModel(modelName: string): Promise<void> {
    await this.openModelList(modelName);
    await this.chooseModelOption(this.modelOption(modelName).first());
  }

  // ---------------------------------------------------------------------------
  // Message assertions
  // ---------------------------------------------------------------------------

  async expectHumanMessage(text: string, index = 0): Promise<void> {
    await expect(this.humanMessage(index)).toContainText(text);
  }

  async expectNoHumanMessages(): Promise<void> {
    await expect(this.humanMessages).toHaveCount(0);
  }

  async sendUntilUsageLimit(maxTurns: number): Promise<void> {
    for (
      let turn = 0;
      turn < maxTurns && !(await this.usageLimitBanner.isVisible());
      turn++
    ) {
      await this.inputBar.fill(`write a few sentences about topic ${turn}`);
      await this.inputBar.send();
      await Promise.race([
        this.usageLimitBanner
          .waitFor({ state: "visible", timeout: 45_000 })
          .catch(() => {}),
        this.aiMessage(turn)
          .waitFor({ state: "visible", timeout: 45_000 })
          .catch(() => {}),
      ]);
    }
  }

  async expectAccountUsageLimit(): Promise<void> {
    await expect(this.usageLimitBanner).toBeVisible();
    await expect(this.page.getByText(/your account/i)).toBeVisible();
  }
}
