import { type Locator, type Page, expect } from "@playwright/test";

/** The approval card a chat answer shows when a tool call needs a decision. */
export class ToolApprovalCard {
  readonly page: Page;
  readonly cards: Locator;
  readonly card: Locator;
  readonly approveButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.cards = page.getByTestId("tool-approval-card");
    this.card = this.cards.last();
    this.approveButton = this.card.getByRole("button", {
      name: "Approve this action once",
      exact: true,
    });
  }

  async expectPending(toolName: string): Promise<void> {
    // The header names the action and its deadline.
    await expect(
      this.card.getByRole("button", {
        name: new RegExp(`^Approval requested: ${toolName} Approve by`),
      })
    ).toBeVisible({ timeout: 30_000 });
  }

  async expectArgument(value: string): Promise<void> {
    // A waiting request shows its details.
    await expect(this.card.getByText(value, { exact: true })).toBeVisible();
  }

  async approve(): Promise<void> {
    await this.approveButton.click();
  }

  async approveForChat(): Promise<void> {
    await this.card
      .getByRole("button", {
        name: "Approve now and run this tool without asking again for the rest of this chat",
        exact: true,
      })
      .click();
  }

  async reject(): Promise<void> {
    await this.card
      .getByRole("button", { name: "Reject this action", exact: true })
      .click();
  }

  /** A blocked send warns and brings the waiting card into view. */
  async expectSendBlocked(): Promise<void> {
    await expect(
      this.page.getByText("Approve or reject the pending tool calls first.", {
        exact: true,
      })
    ).toBeVisible();
    await expect(this.card).toBeInViewport();
  }

  /** A decided or closed request leaves a one-line record. */
  async expectRecord(prefix: string, timeout?: number): Promise<void> {
    await expect(this.card.getByRole("status")).toHaveText(
      new RegExp(`^${prefix}: `),
      { timeout }
    );
    await expect(this.approveButton).toHaveCount(0);
  }

  async expectApproved(): Promise<void> {
    await this.expectRecord("Approved");
  }

  async expectApprovedForChat(): Promise<void> {
    await this.expectRecord("Approved for this chat");
  }

  async expectNotApproved(): Promise<void> {
    await this.expectRecord("Not approved");
  }

  /**
   * The request stopped waiting without a decision, e.g. after Stop. The card
   * shows "No longer waiting" until the saved response, which shows no card,
   * replaces the streamed one.
   */
  async expectClosed(): Promise<void> {
    await expect(this.approveButton).toHaveCount(0, { timeout: 30_000 });
  }
}
