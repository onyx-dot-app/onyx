import { type Locator, type Page, expect } from "@playwright/test";

/** An option's accessible name, which also holds its description. */
function optionName(option: string): RegExp {
  return new RegExp(`^${option.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}( |$)`);
}

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
      await expect(
        this.card.getByRole("radio").nth(index)
      ).toHaveAccessibleName(optionName(option));
  }

  async choose(option: string): Promise<void> {
    await this.card
      .getByRole("radio")
      .filter({ has: this.page.getByText(option, { exact: true }) })
      .click();
  }

  /** The hint that a multi-select question shows. */
  async expectMultiSelectHint(): Promise<void> {
    await expect(
      this.card.getByText("Choose all that apply.", { exact: true })
    ).toBeVisible();
  }

  /** Toggles an option of a multi-select question. */
  async toggle(option: string): Promise<void> {
    await this.card
      .getByRole("checkbox")
      .filter({ has: this.page.getByText(option, { exact: true }) })
      .click();
  }

  /** The options of a multi-select question that are chosen. */
  async expectChecked(options: string[]): Promise<void> {
    const checked = this.card.getByRole("checkbox", { checked: true });
    await expect(checked).toHaveCount(options.length);
    for (const [index, option] of options.entries())
      await expect(checked.nth(index)).toHaveAccessibleName(optionName(option));
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
   * The record of the questions: a timeline step titled with the answers, or
   * else with how the questions ended (`title` defaults to `outcome`). Its
   * live region announces the outcome. Nothing waits after it.
   */
  async expectRecord(
    outcome: string,
    title = outcome,
    timeout = 30_000
  ): Promise<void> {
    const record = this.records.filter({
      has: this.page.getByRole("button", {
        name: `Expand ${title}`,
        exact: true,
      }),
    });
    await expect(record.getByRole("status")).toHaveText(outcome, { timeout });
    await expect(this.region).toHaveCount(0);
  }
}
