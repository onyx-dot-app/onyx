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

  constructor(page: Page) {
    this.page = page;
    this.inputBar = new InputBar(page);
    this.container = page.locator("[data-main-container]");
    this.scrollContainer = page.getByTestId("chat-scroll-container");
    this.humanMessages = page.locator("#onyx-human-message");
    this.aiMessages = page.getByTestId("onyx-ai-message");
    this.usageLimitBanner = page.getByText(/you've reached the usage budget/i);
  }

  humanMessage(index = 0): Locator {
    return this.humanMessages.nth(index);
  }

  aiMessage(index = 0): Locator {
    return this.aiMessages.nth(index);
  }

  async goto(sessionId?: string): Promise<void> {
    await this.page.goto(sessionId ? `/app?chatId=${sessionId}` : "/app");
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
  // Message assertions
  // ---------------------------------------------------------------------------

  async expectAnswerParagraph(text: string): Promise<void> {
    await expect(
      this.scrollContainer.getByText(text, { exact: true })
    ).toHaveCount(1);
  }

  async expectAnswerHeading(text: string): Promise<void> {
    await expect(
      this.scrollContainer.getByRole("heading", { name: text, exact: true })
    ).toHaveCount(1);
  }

  async expectAnswerTable(headers: string[], rows: number): Promise<void> {
    const table = this.aiMessage().getByRole("table");
    await expect(table.getByRole("columnheader")).toHaveText(headers);
    await expect(table.getByRole("row")).toHaveCount(rows);
  }

  async expectAnswerListItem(text: string): Promise<void> {
    await expect(
      this.aiMessage().getByRole("listitem").filter({ hasText: text })
    ).toHaveCount(1);
  }

  async expectCopyButton(): Promise<void> {
    await expect(
      this.aiMessage().getByTestId("AgentMessage/copy-button")
    ).toBeVisible();
  }

  async expectAnswerCode(text: string): Promise<void> {
    await expect(this.aiMessage().getByRole("code")).toContainText(text);
  }

  async expectAnswerAbsent(text: string): Promise<void> {
    await expect(this.scrollContainer).not.toContainText(text);
  }

  async expectCompleteAnswers(count: number): Promise<void> {
    await expect(this.aiMessages).toHaveCount(count);
    await expect(this.inputBar.sendButton).toBeDisabled();
  }

  async expectCustomToolResult(name: string, json: string): Promise<void> {
    await this.page
      .getByRole("button", { name: "Expand timeline", exact: true })
      .click();
    const status = this.scrollContainer.getByText(`${name} completed`, {
      exact: true,
    });
    await expect(status).toBeVisible();
    await status.click();
    await expect(
      this.scrollContainer.getByRole("code").filter({ hasText: json })
    ).toBeVisible();
  }

  async startIncognito(): Promise<void> {
    await this.page
      .getByRole("button", { name: "Start incognito chat" })
      .click();
    await expect(this.page.getByTestId("incognito-intro")).toBeVisible();
  }

  async expectIncognito(): Promise<void> {
    await expect(this.page.getByTestId("incognito-chat-pill")).toBeVisible();
    await expect(
      this.page.getByRole("button", { name: "share-chat-button" })
    ).toHaveCount(0);
    await expect(this.page.getByTestId("AgentMessage/like-button")).toHaveCount(
      0
    );
  }

  async exitIncognito(): Promise<void> {
    await this.page
      .getByRole("button", { name: "Exit incognito chat" })
      .click();
    await expect(this.page.getByTestId("incognito-chat-pill")).toHaveCount(0);
    await this.expectNoHumanMessages();
  }

  async expectNoSessionLink(sessionId: string): Promise<void> {
    await expect(
      this.page.locator(`a[href="/app?chatId=${sessionId}"]`)
    ).toHaveCount(0);
  }

  async expectStopping(): Promise<void> {
    await expect(this.inputBar.sendButton).toBeDisabled();
    await expect(this.inputBar.sendButton).toHaveText("Stopping…");
  }

  async stop(): Promise<void> {
    await this.inputBar.expectEmpty();
    await this.inputBar.sendButton.click();
  }

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
