/**
 * Page Object Model for the Security & Hardening admin page (/admin/security).
 *
 * Encapsulates the toggle rows (each rendered as an Opal <Switch> inside an
 * InputHorizontal <label>) and the save-confirmation toast so specs stay
 * declarative and locator churn is confined to this file.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class AdminSecurityPage {
  readonly page: Page;
  readonly savedToast: Locator;

  // A stable, always-present, tenant-editable toggle — used as the subject for
  // round-trip persistence checks (visible in both single- and multi-tenant).
  static readonly SESSION_EXPIRY_TOGGLE =
    "Sync Session Expiry with Identity Provider";

  constructor(page: Page) {
    this.page = page;
    this.savedToast = page.getByText("Security settings updated");
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  /** Navigate to the page and wait for it to finish loading. */
  async goto(): Promise<void> {
    await this.page.goto("/admin/security");
    await this.waitForLoaded();
  }

  /** Reload the page and wait for it to finish loading. */
  async reload(): Promise<void> {
    await this.page.reload();
    await this.waitForLoaded();
  }

  private async waitForLoaded(): Promise<void> {
    await this.page.waitForLoadState("networkidle");
    await expect(
      this.page.getByText(AdminSecurityPage.SESSION_EXPIRY_TOGGLE)
    ).toBeVisible({ timeout: 10000 });
  }

  // ---------------------------------------------------------------------------
  // Toggle rows
  // ---------------------------------------------------------------------------

  /** The <Switch> control for the toggle row with the given title. */
  toggle(title: string): Locator {
    return this.page
      .getByText(title)
      .locator("xpath=ancestor::label[1]")
      .getByRole("switch");
  }

  /** Whether the named toggle is currently on (aria-checked === "true"). */
  async isToggleOn(title: string): Promise<boolean> {
    return (await this.toggle(title).getAttribute("aria-checked")) === "true";
  }

  /** Flip the named toggle and wait for the save-confirmation toast. */
  async clickToggleAndSave(title: string): Promise<void> {
    await this.toggle(title).click();
    await expect(this.savedToast).toBeVisible({ timeout: 5000 });
  }

  /** Assert the named toggle is in the expected on/off state. */
  async expectToggle(title: string, on: boolean): Promise<void> {
    await expect(this.toggle(title)).toHaveAttribute(
      "aria-checked",
      on ? "true" : "false"
    );
  }
}
