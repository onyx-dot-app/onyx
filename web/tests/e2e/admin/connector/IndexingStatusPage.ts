/**
 * Page Object Model for the connector status page (`/admin/indexing/status`).
 *
 * Encapsulates the locators and interactions used by the visual-regression
 * spec so it stays declarative (see `web/tests/e2e/README.md` §1).
 */

import { expect, type Locator, type Page } from "@playwright/test";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";

export class IndexingStatusPage {
  readonly page: Page;
  readonly pageTitle: Locator;

  constructor(page: Page) {
    this.page = page;
    this.pageTitle = page.locator('[aria-label="admin-page-title"]');
  }

  /**
   * The collapsed summary row for a connector source group, located by its
   * display name (e.g. "File" for the `file` source). Connectors are grouped
   * by source and shown collapsed by default, so the source display name is
   * the stable signal that the table has rendered with data.
   */
  sourceGroup(displayName: string): Locator {
    return this.page.getByText(displayName, { exact: true }).first();
  }

  async goto() {
    await this.page.goto("/admin/indexing/status");
    await expect(this.pageTitle).toBeVisible({ timeout: 10_000 });
  }

  /**
   * Wait for a source group to render so we don't snapshot the loading
   * skeleton, then settle the network before any screenshot.
   */
  async waitForSourceGroup(displayName: string) {
    await expect(this.sourceGroup(displayName)).toBeVisible({
      timeout: 15_000,
    });
    await this.page.waitForLoadState("networkidle");
  }

  /**
   * Capture a full-page visual snapshot. Masks the same dynamic columns the
   * admin-pages sweep masked so the relocated baseline stays comparable.
   */
  async expectScreenshot(name: string) {
    await expectScreenshot(this.page, {
      name,
      mask: [
        '[data-testid="admin-date-range-selector-button"]',
        '[data-column-id="updated_at"]',
      ],
    });
  }
}
