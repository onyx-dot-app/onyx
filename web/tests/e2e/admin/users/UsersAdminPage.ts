/**
 * Page Object Model for the Admin Users page (/admin/users).
 *
 * Encapsulates all locators and interactions so specs remain declarative.
 */

import { type Page, type Locator, expect } from "@playwright/test";

/** URL pattern that matches the users data fetch. */
const USERS_API = /\/api\/manage\/users\/(accepted\/all|invited)/;

export class UsersAdminPage {
  readonly page: Page;

  // Top-level elements
  readonly inviteButton: Locator;
  readonly searchInput: Locator;

  // Filter buttons
  readonly accountTypesFilter: Locator;
  readonly groupsFilter: Locator;
  readonly statusFilter: Locator;

  // Table
  readonly table: Locator;
  readonly tableRows: Locator;

  // Pagination & footer
  readonly paginationSummary: Locator;
  readonly downloadCsvButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.inviteButton = page.getByRole("button", { name: "Invite Users" });
    this.searchInput = page.getByPlaceholder("Search users...");

    this.accountTypesFilter = page.getByRole("button", {
      name: /Account Types/,
    });
    this.groupsFilter = page.getByRole("button", { name: /Groups/ });
    this.statusFilter = page.getByRole("button", { name: /Status/ });

    this.table = page.getByRole("table");
    this.tableRows = page.getByRole("table").locator("tbody tr");

    this.paginationSummary = page.getByText(/Showing \d/);
    this.downloadCsvButton = page.getByRole("button", {
      name: "Download CSV",
    });
  }

  // ---------------------------------------------------------------------------
  // Popover helper
  // ---------------------------------------------------------------------------

  /**
   * Returns a locator for the currently open popover / filter dropdown.
   * Radix Popover renders its content with `role="dialog"`. Using
   * `getByRole("dialog").first()` targets the oldest open dialog, which is
   * always the popover during row-action or filter flows (confirmation
   * modals open later and would be `.last()`).
   */
  get popover(): Locator {
    return this.page.getByRole("dialog").first();
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  async goto() {
    await this.page.goto("/admin/users");
    await expect(this.page.getByText("Users & Requests")).toBeVisible({
      timeout: 15000,
    });
    // Wait for the table to finish loading (pagination summary only appears
    // after the async data fetch completes).
    await expect(this.paginationSummary).toBeVisible({ timeout: 15000 });
  }

  // ---------------------------------------------------------------------------
  // Waiting helpers
  // ---------------------------------------------------------------------------

  /** Wait for the users API response that follows a table-refreshing action. */
  private async waitForTableRefresh(): Promise<void> {
    await this.page.waitForResponse(USERS_API);
  }

  // ---------------------------------------------------------------------------
  // Search
  // ---------------------------------------------------------------------------

  async search(term: string) {
    await this.searchInput.fill(term);
  }

  async clearSearch() {
    await this.searchInput.fill("");
  }

  // ---------------------------------------------------------------------------
  // Filters
  // ---------------------------------------------------------------------------

  async openAccountTypesFilter() {
    await this.accountTypesFilter.click();
    await expect(this.popover).toBeVisible();
  }

  async selectAccountType(label: string) {
    await this.popover.getByText(label, { exact: false }).first().click();
  }

  async openStatusFilter() {
    await this.statusFilter.click();
    await expect(this.popover).toBeVisible();
  }

  async selectStatus(label: string) {
    await this.popover.getByText(label, { exact: false }).first().click();
  }

  async openGroupsFilter() {
    await this.groupsFilter.click();
    await expect(this.popover).toBeVisible();
  }

  async selectGroup(label: string) {
    await this.popover.getByText(label, { exact: false }).first().click();
  }

  async closePopover() {
    await this.page.keyboard.press("Escape");
    await expect(this.page.getByRole("dialog")).not.toBeVisible();
  }

  // ---------------------------------------------------------------------------
  // Table interactions
  // ---------------------------------------------------------------------------

  async getVisibleRowCount(): Promise<number> {
    return await this.tableRows.count();
  }

  /**
   * Returns the text content of a specific column across all visible rows.
   * Column indices: 0=Name, 1=Groups, 2=Account Type, 3=Status, 4=Last Updated.
   */
  async getColumnTexts(columnIndex: number): Promise<string[]> {
    const cells = this.tableRows.locator(`td:nth-child(${columnIndex + 2})`);
    const count = await cells.count();
    const texts: string[] = [];
    for (let i = 0; i < count; i++) {
      const text = await cells.nth(i).textContent();
      if (text) texts.push(text.trim());
    }
    return texts;
  }

  getRowByEmail(email: string): Locator {
    return this.table.getByRole("row").filter({ hasText: email });
  }

  /** Click the sort button on a column header. */
  async sortByColumn(columnName: string) {
    // Column headers are <th> elements. The sort button is a child <button>
    // that only appears on hover — hover first to reveal it.
    const header = this.table.locator("th").filter({ hasText: columnName });
    await header.hover();
    await header.locator("button").first().click();
  }

  // ---------------------------------------------------------------------------
  // Pagination
  // ---------------------------------------------------------------------------

  /** Click a numbered page button in the table footer. */
  async goToPage(pageNumber: number) {
    const footer = this.page.locator(".table-footer");
    await footer
      .getByRole("button")
      .filter({ hasText: String(pageNumber) })
      .click();
  }

  // ---------------------------------------------------------------------------
  // Row actions
  // ---------------------------------------------------------------------------

  async openRowActions(email: string) {
    const row = this.getRowByEmail(email);
    const actionsButton = row.getByRole("button").last();
    await actionsButton.click();
    await expect(this.popover).toBeVisible();
  }

  async clickRowAction(actionName: string) {
    await this.popover.getByText(actionName).first().click();
  }

  // ---------------------------------------------------------------------------
  // Confirmation modals
  // ---------------------------------------------------------------------------

  /**
   * Returns the most recently opened dialog (modal).
   * Uses `.last()` because confirmation modals are portaled after row-action
   * popovers, and a closing popover (role="dialog") may briefly remain in the
   * DOM during its exit animation.
   */
  get dialog(): Locator {
    return this.page.getByRole("dialog").last();
  }

  async confirmModalAction(buttonName: string) {
    await this.dialog.getByRole("button", { name: buttonName }).first().click();
  }

  async cancelModal() {
    await this.dialog.getByRole("button", { name: "Cancel" }).first().click();
  }

  async expectToast(message: string | RegExp) {
    await expect(this.page.getByText(message)).toBeVisible();
  }

  // ---------------------------------------------------------------------------
  // Invite modal
  // ---------------------------------------------------------------------------

  async openInviteModal() {
    await this.inviteButton.click();
    await expect(this.dialog.getByText("Invite Users")).toBeVisible();
  }

  async addInviteEmail(email: string) {
    const input = this.dialog.getByPlaceholder(
      "Add emails to invite, comma separated"
    );
    await input.pressSequentially(email, { delay: 20 });
    await input.press("Enter");
    // Wait for the chip to appear in the dialog
    await expect(this.dialog.getByText(email)).toBeVisible();
  }

  async submitInvite() {
    await this.dialog.getByRole("button", { name: "Invite" }).click();
  }

  // ---------------------------------------------------------------------------
  // Inline role editing (Popover + OpenButton + LineItem)
  // ---------------------------------------------------------------------------

  async openRoleDropdown(email: string) {
    const row = this.getRowByEmail(email);
    const roleButton = row
      .locator("button")
      .filter({ hasText: /Basic|Admin|Global Curator|Slack User/ });
    await roleButton.click();
    await expect(this.popover).toBeVisible();
  }

  async selectRole(roleName: string) {
    await this.popover.getByText(roleName).first().click();
    await this.waitForTableRefresh();
  }

  // ---------------------------------------------------------------------------
  // Edit groups modal
  // ---------------------------------------------------------------------------

  async openEditGroupsModal(email: string) {
    await this.openRowActions(email);
    await this.clickRowAction("Groups");
    await expect(
      this.dialog.getByText("Edit User's Groups & Roles")
    ).toBeVisible();
  }

  async searchGroupsInModal(term: string) {
    await this.dialog.getByPlaceholder("Search groups to join...").fill(term);
    await expect(this.dialog.getByText(term).first()).toBeVisible();
  }

  async toggleGroupInModal(groupName: string) {
    await this.dialog.getByText(groupName).first().click();
  }

  async saveGroupsModal() {
    await this.dialog.getByRole("button", { name: "Save Changes" }).click();
  }
}
