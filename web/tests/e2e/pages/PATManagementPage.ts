/**
 * Page Object Model for the Personal Access Token (PAT) management UI on the
 * account settings page (/app/settings/accounts-access).
 *
 * Encapsulates the "Create Access Token" modal (name, expiration, the Full /
 * Limited permissions selector and its scope checkboxes) and the token list
 * (viewing, copying, and revoking tokens) so specs stay declarative.
 */

import { type Page, type Locator, expect } from "@playwright/test";

const TOKEN_PREFIX = "onyx_pat_";

export class PATManagementPage {
  readonly page: Page;
  readonly newTokenButton: Locator;
  readonly nameInput: Locator;
  readonly createButton: Locator;
  readonly tokenDisplay: Locator;

  constructor(page: Page) {
    this.page = page;
    this.newTokenButton = page.locator('button:has-text("New Access Token")');
    this.nameInput = page.locator('input[placeholder*="Name your token"]');
    this.createButton = page.locator('button:has-text("Create Token")');
    this.tokenDisplay = page.locator("code").filter({ hasText: TOKEN_PREFIX });
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  /** Open Settings from the user dropdown and land on the access-tokens page. */
  async goto(): Promise<void> {
    await this.page.locator("#onyx-user-dropdown").click();
    await this.page.getByText("Settings").first().click();
    await expect(this.page.getByText("Full Name")).toBeVisible();
    await this.page
      .locator('a[href="/app/settings/accounts-access"]')
      .click({ force: true });
    await expect(this.newTokenButton).toBeVisible({ timeout: 10000 });
  }

  // ---------------------------------------------------------------------------
  // Create-token modal
  // ---------------------------------------------------------------------------

  async openCreateModal(): Promise<void> {
    await this.newTokenButton.first().click();
  }

  async fillName(name: string): Promise<void> {
    await this.nameInput.first().fill(name);
  }

  /** Pick an expiration; the combobox defaults to "30 days". */
  async selectExpiration(optionLabel: string): Promise<void> {
    await this.page
      .getByRole("combobox")
      .filter({ hasText: "30 days" })
      .click();
    await this.page.getByRole("option", { name: optionLabel }).click();
  }

  /** Switch the permissions selector from its "Full access" default to Limited. */
  async chooseLimitedAccess(): Promise<void> {
    await this.page
      .getByRole("combobox")
      .filter({ hasText: "Full access" })
      .click();
    await this.page.getByRole("option", { name: "Limited access" }).click();
  }

  /** Toggle a scope checkbox by its accessible name, e.g. "Search Read". */
  async toggleScope(name: string): Promise<void> {
    await this.page.getByRole("checkbox", { name }).click();
  }

  async submit(): Promise<void> {
    await this.createButton.first().click();
  }

  async waitForCreatedToken(): Promise<string> {
    const display = this.tokenDisplay.first();
    await display.waitFor({ state: "visible", timeout: 5000 });
    return (await display.textContent()) ?? "";
  }

  async copyCreatedToken(): Promise<void> {
    await this.page.getByRole("button", { name: "Copy Token" }).click();
  }

  async close(): Promise<void> {
    await this.page.keyboard.press("Escape");
  }

  // ---------------------------------------------------------------------------
  // Token list
  // ---------------------------------------------------------------------------

  async expectListed(name: string): Promise<void> {
    await expect(this.page.getByText(name).first()).toBeVisible({
      timeout: 5000,
    });
  }

  async expectNotListed(name: string): Promise<void> {
    await expect(this.page.locator(`p:text-is("${name}")`)).not.toBeVisible({
      timeout: 5000,
    });
  }

  async expectRowText(pattern: RegExp): Promise<void> {
    await expect(this.page.getByText(pattern).first()).toBeVisible({
      timeout: 5000,
    });
  }

  async revokeToken(name: string): Promise<void> {
    await this.page
      .locator(`button[aria-label="Delete token ${name}"]`)
      .click();
    const confirm = this.page.locator('button:has-text("Revoke")').first();
    await confirm.waitFor({ state: "visible", timeout: 3000 });
    await confirm.click();
    await expect(confirm).not.toBeVisible({ timeout: 3000 });
  }
}
