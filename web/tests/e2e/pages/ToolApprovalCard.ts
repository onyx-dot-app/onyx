import { type Locator, type Page, expect } from "@playwright/test";

/**
 * The approval cards of a chat. A card that waits for a decision shows in the
 * region after the last message; a decided request leaves a one-line record
 * in its reply.
 */
export class ToolApprovalCard {
  readonly page: Page;
  /** Every card and record in the chat. */
  readonly cards: Locator;
  readonly region: Locator;
  /** The newest card that waits for a decision. */
  readonly card: Locator;
  /** The newest record in a reply. */
  readonly record: Locator;
  readonly approveButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.cards = page.getByTestId("tool-approval-card");
    this.region = page.getByTestId("tool-approvals-region");
    this.card = this.region.getByTestId("tool-approval-card").last();
    this.record = page
      .getByTestId("chat-scroll-container")
      .locator('[id^="message-"]')
      .getByTestId("tool-approval-card")
      .last();
    this.approveButton = this.card.getByRole("button", {
      name: "Approve this action once",
      exact: true,
    });
  }

  /** `headline` is the visible header: "{action} in {integration}". A
   * command's request adds its deadline. */
  async expectPending(headline: string): Promise<void> {
    const name = headline.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    await expect(
      this.card.getByRole("button", {
        name: new RegExp(`^Approval requested: ${name}(\\.? ?Approve by .+)?$`),
      })
    ).toBeVisible({ timeout: 30_000 });
  }

  /** The input bar does not cover the waiting card. */
  async expectPendingInView(): Promise<void> {
    await expect(this.card).toBeInViewport();
  }

  async expectArgument(value: string, timeout?: number): Promise<void> {
    // A waiting request shows its details.
    await expect(this.card.getByText(value, { exact: true })).toBeVisible({
      timeout,
    });
  }

  /** The waiting card names the agent that asks. */
  async expectAgentRequest(agent: string, toolName: string): Promise<void> {
    await expect(
      this.card.getByText(`${agent} wants to run ${toolName}`, { exact: true })
    ).toBeVisible();
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
    await this.expectPendingInView();
  }

  /**
   * A decided request leaves a one-line record with the card's headline, in its
   * reply once the resolution arrives. The saved response shows the same
   * record after the answer settles and after a reload. Nothing waits after
   * it.
   */
  async expectRecord(
    record: string,
    headline: string,
    timeout = 30_000
  ): Promise<void> {
    await expect(this.record.getByRole("status")).toHaveText(
      `${record}: ${headline}`,
      { timeout }
    );
    await expect(this.region).toHaveCount(0);
  }

  async expectApproved(headline: string): Promise<void> {
    await this.expectRecord("Approved", headline);
  }

  async expectApprovedForChat(headline: string): Promise<void> {
    await this.expectRecord("Approved for this chat", headline);
  }

  async expectNotApproved(headline: string, timeout?: number): Promise<void> {
    await this.expectRecord("Not approved", headline, timeout);
  }
}
