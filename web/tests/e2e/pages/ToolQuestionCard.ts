import { type Locator, type Page, expect } from "@playwright/test";

/**
 * The question cards of a chat. A card whose questions wait for the user's
 * answers shows in the region after the last message; once the questions
 * end, a record stays in the reply.
 */
export class ToolQuestionCard {
  readonly page: Page;
  readonly region: Locator;
  /** The newest card that waits for answers. */
  readonly card: Locator;
  /** Every record in the chat's replies. */
  readonly records: Locator;

  constructor(page: Page) {
    this.page = page;
    this.region = page.getByTestId("tool-questions-region");
    this.card = this.region.getByTestId("tool-question-card").last();
    this.records = page
      .getByTestId("chat-scroll-container")
      .locator('[id^="message-"]')
      .getByTestId("tool-question-card");
  }

  async expectPending(question: string): Promise<void> {
    await expect(this.card.getByText(question, { exact: true })).toBeVisible({
      timeout: 30_000,
    });
  }

  /** The options, in the order the card shows them. */
  async expectOptions(options: string[]): Promise<void> {
    await expect(this.card.getByRole("radio")).toHaveCount(options.length);
    for (const [index, option] of options.entries())
      // The name also holds the option's description.
      await expect(
        this.card.getByRole("radio").nth(index)
      ).toHaveAccessibleName(
        new RegExp(`^${option.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}( |$)`)
      );
  }

  async choose(option: string): Promise<void> {
    await this.card
      .getByRole("radio")
      .filter({ has: this.page.getByText(option, { exact: true }) })
      .click();
  }

  /** Types the question's "Other" answer. */
  async typeOther(header: string, value: string): Promise<void> {
    await this.other(header).fill(value);
  }

  async expectOther(header: string, value: string): Promise<void> {
    await expect(this.other(header)).toHaveValue(value);
  }

  private other(header: string): Locator {
    return this.card.getByRole("textbox", {
      name: `Other answer to ${header}`,
      exact: true,
    });
  }

  /** The page indicator of a card with more than one question. */
  async expectPage(current: number, total: number): Promise<void> {
    await expect(
      this.card.getByText(`Question ${current} of ${total}`, { exact: true })
    ).toBeVisible();
  }

  async next(): Promise<void> {
    await this.card.getByRole("button", { name: "Next", exact: true }).click();
  }

  async back(): Promise<void> {
    await this.card.getByRole("button", { name: "Back", exact: true }).click();
  }

  /** Submit shows on the last page only. */
  async submit(): Promise<void> {
    await this.card
      .getByRole("button", { name: "Submit", exact: true })
      .click();
  }

  /**
   * The record of the questions that `line` names: how they ended, and a
   * line per question. Nothing waits after it.
   */
  async expectRecord(
    title: string,
    line: string,
    timeout = 30_000
  ): Promise<void> {
    const record = this.records.filter({
      has: this.page.getByText(line, { exact: true }),
    });
    await expect(record.getByRole("status")).toHaveText(title, { timeout });
    await expect(this.region).toHaveCount(0);
  }
}
