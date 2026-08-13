/**
 * Page Object Model for the admin document sets list (/admin/documents/sets).
 *
 * Editability is a per-row stamp from the listing response, not a client-side
 * recompute: an editable row's name navigates to the edit page, a read-only one is
 * inert text. `expectEditable` asserts the behavior rather than the icon, so it can't
 * pass on a row that merely looks clickable.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class AdminDocumentSetsPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(): Promise<void> {
    await this.page.goto("/admin/documents/sets");
  }

  row(name: string): Locator {
    return this.page.getByRole("row", { name: new RegExp(name) });
  }

  async expectListed(name: string): Promise<void> {
    await expect(this.row(name)).toBeVisible({ timeout: 30000 });
  }

  async expectEditable(name: string, documentSetId: number): Promise<void> {
    await this.row(name).getByText(name, { exact: true }).click();
    await expect(this.page).toHaveURL(
      new RegExp(`/admin/documents/sets/${documentSetId}$`)
    );
  }

  /**
   * The delete control is the row's only button, and it renders only when the
   * listing stamps `permissions.delete` — it carries no accessible name of its own
   * (icon-only, tooltip is not a label), so presence is counted rather than named.
   */
  async expectDeleteOffered(name: string, offered: boolean): Promise<void> {
    await expect(this.row(name).getByRole("button")).toHaveCount(
      offered ? 1 : 0
    );
  }
}
