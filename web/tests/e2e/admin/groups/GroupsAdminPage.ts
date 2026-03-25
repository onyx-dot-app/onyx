/**
 * Page Object Model for the Admin Groups page (/admin/groups).
 *
 * Covers the list page, create page, and edit page interactions.
 */

import { type Page, type Locator, expect } from "@playwright/test";

/** URL pattern that matches the groups data fetch. */
const GROUPS_API = /\/api\/manage\/admin\/user-group/;

export class GroupsAdminPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  async goto() {
    await this.page.goto("/admin/groups");
    await expect(this.newGroupButton).toBeVisible({ timeout: 15000 });
  }

  async gotoCreate() {
    await this.page.goto("/admin/groups/create");
    await expect(this.page.getByText("Create Group")).toBeVisible({
      timeout: 15000,
    });
  }

  async gotoEdit(groupId: number) {
    await this.page.goto(`/admin/groups/${groupId}`);
    // Wait for the form to be ready — avoids networkidle hanging due to SWR polling.
    await expect(this.groupNameInput).toBeVisible({ timeout: 15000 });
  }

  // ---------------------------------------------------------------------------
  // List page
  // ---------------------------------------------------------------------------

  /** The Groups page heading container (unique to the list page). */
  get pageHeading(): Locator {
    return this.page.getByTestId("groups-page-heading");
  }

  /** The search input on the list page. */
  get listSearchInput(): Locator {
    return this.page.getByPlaceholder("Search groups...");
  }

  /** The "New Group" button on the list page header. */
  get newGroupButton(): Locator {
    return this.page.getByRole("button", { name: "New Group" });
  }

  /** Returns all group cards on the list page. */
  get groupCards(): Locator {
    return this.page.locator("[data-card]");
  }

  /**
   * Returns a group card by name.
   * Cards use ContentAction which renders the title as text — match by content.
   */
  getGroupCard(name: string): Locator {
    return this.page.locator("[data-card]").filter({ hasText: name });
  }

  /** Click into a group's edit page from the list. */
  async openGroup(name: string) {
    const card = this.getGroupCard(name);
    await card.getByRole("button", { name: "View group" }).click();
    await expect(this.groupNameInput).toBeVisible({ timeout: 15000 });
  }

  /** Search groups on the list page. */
  async searchGroups(term: string) {
    await this.listSearchInput.fill(term);
  }

  /** Click "New Group" to navigate to the create page. */
  async clickNewGroup() {
    await this.newGroupButton.click();
    await expect(this.page.getByText("Create Group")).toBeVisible({
      timeout: 15000,
    });
  }

  // ---------------------------------------------------------------------------
  // Create page
  // ---------------------------------------------------------------------------

  /** The group name input on create/edit pages. */
  get groupNameInput(): Locator {
    return this.page.getByPlaceholder("Name your group");
  }

  /** The member search input on create/edit pages. */
  get memberSearchInput(): Locator {
    return this.page.getByPlaceholder("Search users and accounts...");
  }

  /** The "Create" button on the create page. */
  get createButton(): Locator {
    return this.page.getByRole("button", { name: "Create", exact: true });
  }

  /** The "Cancel" button on create/edit pages. */
  get cancelButton(): Locator {
    return this.page.getByRole("button", { name: "Cancel" });
  }

  /** Fill in the group name on create/edit pages. */
  async setGroupName(name: string) {
    await this.groupNameInput.fill(name);
  }

  /** Search for members in the members table. */
  async searchMembers(term: string) {
    await this.memberSearchInput.fill(term);
  }

  /** Select a member row by checking their checkbox (create page / add mode). */
  async selectMember(emailOrName: string) {
    const row = this.page.getByRole("row").filter({ hasText: emailOrName });
    const checkbox = row.getByRole("checkbox");
    await checkbox.click();
  }

  /** Submit the create form. */
  async submitCreate() {
    await this.createButton.click();
  }

  // ---------------------------------------------------------------------------
  // Edit page
  // ---------------------------------------------------------------------------

  /** The "Save Changes" button on the edit page. */
  get saveButton(): Locator {
    return this.page.getByRole("button", { name: "Save Changes" });
  }

  /** The "Add" button to enter add-members mode. */
  get addMembersButton(): Locator {
    return this.page.getByRole("button", { name: "Add" });
  }

  /** The "Done" button to exit add-members mode. */
  get doneAddingButton(): Locator {
    return this.page.getByRole("button", { name: "Done" });
  }

  /** The "Delete Group" button in the danger zone card. */
  get deleteGroupButton(): Locator {
    return this.page.getByRole("button", { name: "Delete Group" });
  }

  /** Enter add-members mode on the edit page. */
  async startAddingMembers() {
    await this.addMembersButton.click();
    await expect(this.doneAddingButton).toBeVisible();
  }

  /** Exit add-members mode. */
  async finishAddingMembers() {
    await this.doneAddingButton.click();
    await expect(this.addMembersButton).toBeVisible();
  }

  /**
   * Remove a member from the member view via the minus button.
   * Only works in member view (not add mode).
   */
  async removeMember(emailOrName: string) {
    const row = this.page.getByRole("row").filter({ hasText: emailOrName });
    // The remove button is an IconButton with SvgMinusCircle in the actions column
    await row.getByRole("button").last().click();
  }

  /** Save the edit form. */
  async submitEdit() {
    await this.saveButton.click();
  }

  // ---------------------------------------------------------------------------
  // Delete flow
  // ---------------------------------------------------------------------------

  /** Click "Delete Group" to open the confirmation modal. */
  async clickDeleteGroup() {
    await this.deleteGroupButton.click();
  }

  /** The delete confirmation modal. */
  get deleteModal(): Locator {
    return this.page.getByRole("dialog");
  }

  /** Confirm deletion in the modal. */
  async confirmDelete() {
    await this.deleteModal.getByRole("button", { name: "Delete" }).click();
  }

  /** Cancel deletion in the modal. */
  async cancelDelete() {
    // The modal close button (X icon) or clicking outside
    await this.deleteModal
      .getByRole("button")
      .filter({ hasText: /close|cancel/i })
      .first()
      .click();
  }

  // ---------------------------------------------------------------------------
  // Assertions
  // ---------------------------------------------------------------------------

  async expectToast(message: string | RegExp) {
    await expect(this.page.getByText(message)).toBeVisible({ timeout: 10000 });
  }

  /** Assert a group card exists on the list page. */
  async expectGroupVisible(name: string) {
    await expect(this.getGroupCard(name)).toBeVisible({ timeout: 10000 });
  }

  /** Assert a group card does NOT exist on the list page. */
  async expectGroupNotVisible(name: string) {
    await expect(this.getGroupCard(name)).not.toBeVisible({ timeout: 10000 });
  }

  /** Assert we navigated back to the groups list. */
  async expectOnListPage() {
    await expect(this.page).toHaveURL(/\/admin\/groups\/?$/);
    await expect(this.newGroupButton).toBeVisible();
  }

  /** Assert we are on the edit page for a specific group. */
  async expectOnEditPage(groupId: number) {
    await expect(this.page).toHaveURL(`/admin/groups/${groupId}`);
  }

  /** Wait for the groups API response after a mutation. */
  async waitForGroupsRefresh() {
    await this.page.waitForResponse(GROUPS_API);
  }
}
