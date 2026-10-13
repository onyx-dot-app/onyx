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
  /** The attempt history at the bottom of the page. */
  readonly runsSection: Locator;
  /** Opens the action menu; present only when the caller may edit. */
  readonly manageButton: Locator;
  readonly deleteMenuItem: Locator;
  /** Enters the inline file editor of a file connector. */
  readonly filesEditButton: Locator;
  /** Opens the connector in the creation form in edit mode. */
  readonly editConnectorMenuItem: Locator;
  /** Unfolds the section listing the connector's settings. */
  readonly indexConfigurationsToggle: Locator;

  constructor(page: Page) {
    this.page = page;
    this.indexingSection = page.getByTestId("connector-indexing-status");
    this.runsSection = page.getByText("Index Runs", { exact: true });
    // without exact, a "managed-*" connector's title button also matches
    this.manageButton = page.getByRole("button", {
      name: "Manage",
      exact: true,
    });
    this.deleteMenuItem = page.getByRole("menuitem", { name: /Delete/i });
    // By id: the header's title pencil is also a button named "Edit".
    this.filesEditButton = page.getByTestId("file-manager-edit");
    this.editConnectorMenuItem = page.getByRole("menuitem", {
      name: "Edit connector",
      exact: true,
    });
    this.indexConfigurationsToggle = page.getByRole("button", {
      name: "Expand Index Configurations",
    });
  }

  /** Unfolds Index Configurations and checks that a setting shows `value`. */
  async expectIndexConfigurationValue(value: string): Promise<void> {
    await this.indexConfigurationsToggle.click();
    await expect(this.page.getByText(value).first()).toBeVisible();
  }

  async openFilesEditor(): Promise<void> {
    await this.filesEditButton.click();
  }

  async goto(ccPairId: number): Promise<void> {
    await this.page.goto(`/admin/connector/${ccPairId}`);
  }

  async expectLoaded(): Promise<void> {
    await expect(this.indexingSection).toBeVisible({ timeout: 30000 });
  }

  async expectRunsVisible(): Promise<void> {
    await expect(this.runsSection).toBeVisible({ timeout: 30000 });
  }

  async openManageMenu(): Promise<void> {
    await expect(this.manageButton).toBeVisible({ timeout: 30000 });
    await this.manageButton.click();
  }

  async openEditForm(): Promise<void> {
    await this.openManageMenu();
    await expect(this.editConnectorMenuItem).toBeVisible({ timeout: 30000 });
    await this.editConnectorMenuItem.click();
  }

  /** The connector name in the page header. */
  async expectName(name: string): Promise<void> {
    await expect(
      this.page.getByText(name, { exact: true }).first()
    ).toBeVisible({ timeout: 30000 });
  }

  async expectDeleteOffered(offered: boolean): Promise<void> {
    if (offered) {
      await expect(this.deleteMenuItem).toBeVisible();
    } else {
      await expect(this.deleteMenuItem).toHaveCount(0);
    }
  }

  /** The error page the detail page renders when the cc-pair fetch is refused. */
  async expectNotAccessible(): Promise<void> {
    await expect(
      this.page.getByText(/Failed to fetch info on Connector with ID/i)
    ).toBeVisible({ timeout: 30000 });
  }
}
