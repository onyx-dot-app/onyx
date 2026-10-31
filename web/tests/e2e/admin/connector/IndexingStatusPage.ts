/**
 * Page Object Model for the connector status page (`/admin/indexing-status`).
 *
 * Encapsulates the locators and interactions used by the visual-regression
 * spec so it stays declarative (see `web/tests/e2e/README.md` §1).
 */

import { expect, type Locator, type Page } from "@playwright/test";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";

const MANAGE_LINK_NAME = "Manage";

export class IndexingStatusPage {
  readonly page: Page;
  readonly pageTitle: Locator;

  constructor(page: Page) {
    this.page = page;
    this.pageTitle = page.locator('[aria-label="admin-page-title"]');
  }

  async goto() {
    await this.page.goto("/admin/indexing-status");
    await expect(this.pageTitle).toBeVisible({ timeout: 10_000 });
  }

  /**
   * The card for an individual connector, located by its exact name. Every
   * connector is listed flat, so the card is the stable signal that the list
   * has rendered with data.
   */
  connectorRow(connectorName: string): Locator {
    return this.page
      .getByTestId(/^indexing-connector-\d+$/)
      .filter({ hasText: connectorName })
      .first();
  }

  /** The link to the connector's detail page, offered only on rows the viewer can manage. */
  manageLink(connectorName: string): Locator {
    // Exact, so a connector whose name contains "manage" does not match through its own name link.
    return this.connectorRow(connectorName).getByRole("link", {
      name: MANAGE_LINK_NAME,
      exact: true,
    });
  }

  /**
   * Wait for a connector's card to render so we don't snapshot the loading
   * skeleton, then settle the network before any screenshot.
   */
  async waitForConnector(connectorName: string) {
    await expect(this.connectorRow(connectorName)).toBeVisible({
      timeout: 15_000,
    });
    await this.page.waitForLoadState("networkidle");
  }

  /**
   * Open a connector's detail page (`/admin/connector/<ccPairId>`) through
   * its manage link. Returns the ccPairId from the URL.
   */
  async openConnector(connectorName: string): Promise<number> {
    await this.manageLink(connectorName).click();
    await this.page.waitForURL(/\/admin\/connector\/\d+/, {
      timeout: 15_000,
    });
    const match = this.page.url().match(/\/admin\/connector\/(\d+)/);
    if (!match) {
      throw new Error(
        `Expected a connector detail URL, got: ${this.page.url()}`
      );
    }
    return Number(match[1]);
  }

  async expectRowOpens(connectorName: string, ccPairId: number) {
    await expect(this.manageLink(connectorName)).toBeVisible();
    expect(await this.openConnector(connectorName)).toBe(ccPairId);
  }

  async expectRowInert(connectorName: string) {
    const row = this.connectorRow(connectorName);
    await expect(row).toBeVisible();
    await expect(this.manageLink(connectorName)).toHaveCount(0);

    // Arm the watcher before the click. Asserting the URL afterwards cannot fail,
    // because it matches the page we are already on and passes on the first poll.
    const navigated = this.page
      .waitForURL(/\/admin\/connector\/\d+/, { timeout: 3_000 })
      .then(() => true)
      .catch(() => false);

    await row.click();
    expect(await navigated).toBe(false);
  }

  /** Capture a full-page visual snapshot. */
  async expectScreenshot(name: string) {
    await expectScreenshot(this.page, { name });
  }
}
