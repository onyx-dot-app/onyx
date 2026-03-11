/**
 * Page Object Model for the Admin Users page (/admin/users).
 *
 * Encapsulates all locators and interactions so specs remain declarative.
 */

import { type Page, type Locator, expect } from "@playwright/test";

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

  // Pagination
  readonly paginationSummary: Locator;

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
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  async goto() {
    await this.page.goto("/admin/users");
    await expect(this.page.getByText("Users & Requests")).toBeVisible({
      timeout: 15000,
    });
  }

  // ---------------------------------------------------------------------------
  // Search
  // ---------------------------------------------------------------------------

  async search(term: string) {
    await this.searchInput.fill(term);
    await this.page.waitForTimeout(300);
  }

  async clearSearch() {
    await this.searchInput.fill("");
    await this.page.waitForTimeout(300);
  }

  // ---------------------------------------------------------------------------
  // Filters
  // ---------------------------------------------------------------------------

  async openAccountTypesFilter() {
    await this.accountTypesFilter.click();
    await expect(
      this.page
        .getByRole("dialog")
        .or(this.page.locator("[data-radix-popper-content-wrapper]"))
    ).toBeVisible();
  }

  async selectAccountType(label: string) {
    const popover = this.page.locator("[data-radix-popper-content-wrapper]");
    await popover.getByRole("button", { name: new RegExp(label) }).click();
  }

  async openStatusFilter() {
    await this.statusFilter.click();
    await expect(
      this.page.locator("[data-radix-popper-content-wrapper]")
    ).toBeVisible();
  }

  async selectStatus(label: string) {
    const popover = this.page.locator("[data-radix-popper-content-wrapper]");
    await popover.getByRole("button", { name: new RegExp(label) }).click();
  }

  async openGroupsFilter() {
    await this.groupsFilter.click();
    await expect(
      this.page.locator("[data-radix-popper-content-wrapper]")
    ).toBeVisible();
  }

  async selectGroup(label: string) {
    const popover = this.page.locator("[data-radix-popper-content-wrapper]");
    await popover.getByRole("button", { name: new RegExp(label) }).click();
  }

  async closePopover() {
    await this.page.keyboard.press("Escape");
    await this.page.waitForTimeout(200);
  }

  // ---------------------------------------------------------------------------
  // Table interactions
  // ---------------------------------------------------------------------------

  async getVisibleRowCount(): Promise<number> {
    return await this.tableRows.count();
  }

  getRowByEmail(email: string): Locator {
    return this.table.getByRole("row").filter({ hasText: email });
  }

  async sortByColumn(columnName: string) {
    const header = this.table
      .getByRole("columnheader")
      .filter({ hasText: columnName });
    await header.getByRole("button").first().click();
    await this.page.waitForTimeout(300);
  }

  // ---------------------------------------------------------------------------
  // Row actions
  // ---------------------------------------------------------------------------

  async openRowActions(email: string) {
    const row = this.getRowByEmail(email);
    const actionsButton = row.getByRole("button").last();
    await actionsButton.click();
    await expect(
      this.page.locator("[data-radix-popper-content-wrapper]")
    ).toBeVisible();
  }

  async clickRowAction(actionName: string) {
    const popover = this.page.locator("[data-radix-popper-content-wrapper]");
    await popover.getByRole("button", { name: actionName }).click();
  }

  // ---------------------------------------------------------------------------
  // Confirmation modals
  // ---------------------------------------------------------------------------

  get dialog(): Locator {
    return this.page.getByRole("dialog");
  }

  async confirmModalAction(buttonName: string) {
    await this.dialog.getByRole("button", { name: buttonName }).click();
  }

  async cancelModal() {
    await this.dialog.getByRole("button", { name: "Cancel" }).click();
  }

  async expectToast(message: string | RegExp) {
    await expect(this.page.getByText(message)).toBeVisible({ timeout: 10000 });
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
    await input.fill(email + ",");
    await this.page.waitForTimeout(200);
  }

  async submitInvite() {
    await this.dialog.getByRole("button", { name: "Invite" }).click();
  }

  // ---------------------------------------------------------------------------
  // Inline role editing (Popover + OpenButton + LineItem)
  // ---------------------------------------------------------------------------

  async openRoleDropdown(email: string) {
    const row = this.getRowByEmail(email);
    // The role cell renders an OpenButton inside a Popover.Trigger
    const roleButton = row
      .locator("button")
      .filter({ hasText: /Basic|Admin|Global Curator|Slack User/ });
    await roleButton.click();
    await expect(
      this.page.locator("[data-radix-popper-content-wrapper]")
    ).toBeVisible();
  }

  async selectRole(roleName: string) {
    const popover = this.page
      .locator("[data-radix-popper-content-wrapper]")
      .last();
    await popover.getByRole("button", { name: roleName }).click();
    await this.page.waitForTimeout(500);
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
    await this.page.waitForTimeout(300);
  }

  async toggleGroupInModal(groupName: string) {
    await this.dialog
      .getByRole("button", { name: new RegExp(groupName) })
      .first()
      .click();
    await this.page.waitForTimeout(200);
  }

  async saveGroupsModal() {
    await this.dialog.getByRole("button", { name: "Save Changes" }).click();
  }
}
