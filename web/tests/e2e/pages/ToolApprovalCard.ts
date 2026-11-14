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

  /**
   * A decided request leaves a one-line record that names the tool. The
   * saved response shows the same record after the answer settles and after
   * a reload.
   */
  async expectRecord(
    record: string,
    toolName: string,
    timeout?: number
  ): Promise<void> {
    await expect(this.card.getByRole("status")).toHaveText(
      `${record}: ${toolName}`,
      { timeout }
    );
    await expect(this.approveButton).toHaveCount(0);
  }

  async expectApproved(toolName: string): Promise<void> {
    await this.expectRecord("Approved", toolName);
  }

  async expectApprovedForChat(toolName: string): Promise<void> {
    await this.expectRecord("Approved for this chat", toolName);
  }

  async expectNotApproved(toolName: string, timeout?: number): Promise<void> {
    await this.expectRecord("Not approved", toolName, timeout);
  }
}
