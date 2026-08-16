/**
 * Page Object Model for the connector detail page (/admin/connector/{ccPairId}).
 *
 * The page gates its whole render on the cc-pair AND index-attempts fetches, and the
 * paginated hook never clears isLoading on error — so a denied sub-resource shows as a
 * permanent spinner, not an error. `expectLoaded` is what distinguishes the two.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class AdminConnectorDetailPage {
  readonly page: Page;

  /** Rendered only once the cc-pair has resolved. */
  readonly indexingSection: Locator;
  /** Opens the action menu; present only when the caller may edit. */
  readonly manageButton: Locator;
  readonly deleteMenuItem: Locator;

  constructor(page: Page) {
    this.page = page;
    this.indexingSection = page.getByText("Documents Indexed", { exact: true });
    // without exact, a "managed-*" connector's title button also matches
    this.manageButton = page.getByRole("button", {
      name: "Manage",
      exact: true,
    });
    this.deleteMenuItem = page.getByRole("menuitem", { name: /Delete/i });
  }

  async goto(ccPairId: number): Promise<void> {
    await this.page.goto(`/admin/connector/${ccPairId}`);
  }

  async expectLoaded(): Promise<void> {
    await expect(this.indexingSection).toBeVisible({ timeout: 30000 });
  }

  async openManageMenu(): Promise<void> {
    await expect(this.manageButton).toBeVisible({ timeout: 30000 });
    await this.manageButton.click();
  }

  async expectDeleteOffered(offered: boolean): Promise<void> {
    if (offered) {
      await expect(this.deleteMenuItem).toBeVisible();
    } else {
      await expect(this.deleteMenuItem).toHaveCount(0);
    }
  }

  /** The error callout the page renders when the cc-pair fetch is refused. */
  async expectNotAccessible(): Promise<void> {
    await expect(
      this.page.getByText(/Failed to fetch info on Connector with ID/i)
    ).toBeVisible({ timeout: 30000 });
  }
}
