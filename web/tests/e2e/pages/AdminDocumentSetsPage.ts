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
    return this.page
      .getByRole("row")
      .filter({ has: this.page.getByText(name, { exact: true }) });
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

  /** Icon-only with no accessible name, and an editable row's name is a button
   *  too — so name the control instead of counting buttons. */
  async expectDeleteOffered(name: string, offered: boolean): Promise<void> {
    await expect(this.row(name).getByTestId("delete-button")).toHaveCount(
      offered ? 1 : 0
    );
  }
}
