/**
 * Page Object Model for the Spending Limits admin page (/admin/spending-limits).
 * Each card (workspace pool, workspace per-user, a group's pool or per-member)
 * is addressed by its API path, e.g. `workspace/per-user`.
 */

import { type Locator, type Page, expect } from "@playwright/test";

export class AdminSpendingLimitsPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(): Promise<void> {
    await this.page.goto("/admin/spending-limits");
    await expect(this.card("workspace/pool")).toBeVisible();
  }

  async reload(): Promise<void> {
    await this.page.reload();
    await expect(this.card("workspace/pool")).toBeVisible();
  }

  card(path: string): Locator {
    return this.page.getByTestId(`spending-limit-card-${path}`);
  }

  /** Adds an all-models limit to the card and fills its token budget, in
   *  thousands of tokens. */
  async addTokenLimit(path: string, thousands: number): Promise<void> {
    const card = this.card(path);
    await card.getByRole("button", { name: "Add Limit" }).click();
    await card
      .getByPlaceholder("No token limit")
      .last()
      .fill(String(thousands));
  }

  async save(path: string): Promise<void> {
    await this.card(path).getByRole("button", { name: "Save Updates" }).click();
    await expect(this.page.getByText("Spending limits saved")).toBeVisible();
  }

  async expectTokenLimit(path: string, thousands: number): Promise<void> {
    await expect(
      this.card(path).getByPlaceholder("No token limit")
    ).toHaveValue(String(thousands));
  }
}
