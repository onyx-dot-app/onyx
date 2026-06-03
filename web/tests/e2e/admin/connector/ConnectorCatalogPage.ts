/**
 * Page Object Model for the connector catalog (`/admin/connectors`).
 *
 * Every source renders as a card whose add button is labelled
 * "Connect <name>". Popular sources appear twice (in the popular grid and in
 * their category), so actions target the first match.
 */

import { expect, type Locator, type Page } from "@playwright/test";

export class ConnectorCatalogPage {
  readonly page: Page;
  readonly pageTitle: Locator;

  constructor(page: Page) {
    this.page = page;
    this.pageTitle = page.locator('[aria-label="admin-page-title"]');
  }

  async goto() {
    await this.page.goto("/admin/connectors");
    await expect(this.pageTitle).toBeVisible({ timeout: 10_000 });
  }

  /** The add button on a source's card, by the source's display name. */
  connectButton(displayName: string): Locator {
    return this.page
      .getByRole("button", { name: `Connect ${displayName}` })
      .first();
  }

  /** Open a source's setup flow from its card. */
  async openSource(displayName: string) {
    await this.connectButton(displayName).click();
    await this.page.waitForLoadState("networkidle");
  }
}
