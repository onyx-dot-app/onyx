/**
 * Page Object Model for the Admin Appearance / Theme page (/admin/theme).
 *
 * Encapsulates locators and interactions for the custom help link and
 * hide-onyx-branding controls so specs stay declarative. Existing tests in
 * `appearance_theme_settings.spec.ts` still use inline locators; new tests
 * should drive the page through this class.
 */

import { expect, type Locator, type Page, type Response } from "@playwright/test";

const ENTERPRISE_SETTINGS_PUT = (r: Response) =>
  r.url().includes("/api/admin/enterprise-settings") &&
  r.request().method() === "PUT";

export class AppearanceThemePage {
  readonly page: Page;

  // Form inputs
  readonly customHelpLinkUrlInput: Locator;
  readonly customHelpLinkLabelInput: Locator;
  readonly hideBrandingToggle: Locator;
  readonly saveButton: Locator;

  // Sidebar / popover
  readonly userDropdownTrigger: Locator;
  readonly customHelpLinkItem: Locator;

  constructor(page: Page) {
    this.page = page;
    this.customHelpLinkUrlInput = page.locator(
      '[data-label="custom-help-link-url-input"]'
    );
    this.customHelpLinkLabelInput = page.locator(
      '[data-label="custom-help-link-label-input"]'
    );
    this.hideBrandingToggle = page.locator(
      '[data-label="hide-onyx-branding-toggle"]'
    );
    this.saveButton = page.getByRole("button", { name: "Apply Changes" });

    this.userDropdownTrigger = page.locator("#onyx-user-dropdown");
    this.customHelpLinkItem = page.getByTestId("Settings/custom-help-link");
  }

  // ---------------------------------------------------------------------------
  // Form interactions
  // ---------------------------------------------------------------------------

  async fillCustomHelpLink(url: string, label?: string) {
    await this.customHelpLinkUrlInput.fill(url);
    if (label !== undefined) {
      await this.customHelpLinkLabelInput.fill(label);
    }
  }

  async fillCustomHelpLinkLabelOnly(label: string) {
    await this.customHelpLinkLabelInput.fill(label);
  }

  async clearCustomHelpLinkLabel() {
    await this.customHelpLinkLabelInput.clear();
  }

  async toggleHideBranding() {
    await this.hideBrandingToggle.scrollIntoViewIfNeeded();
    await this.hideBrandingToggle.click();
  }

  /**
   * Click "Apply Changes" while a `waitForResponse` is already armed.
   *
   * The promise MUST be created before the click to avoid a race where the
   * response lands before Playwright registers the listener.
   */
  async saveAndWaitForPut(timeoutMs = 10_000): Promise<Response> {
    const responsePromise = this.page.waitForResponse(ENTERPRISE_SETTINGS_PUT, {
      timeout: timeoutMs,
    });
    await expect(this.saveButton).toBeEnabled();
    await this.saveButton.click();
    return responsePromise;
  }

  /** Click Apply Changes without waiting for a PUT — for validation failure paths. */
  async clickSave() {
    await expect(this.saveButton).toBeEnabled();
    await this.saveButton.click();
  }

  async expectSaveSuccessToast(timeoutMs = 5_000) {
    await expect(this.page.getByText(/successfully/i)).toBeVisible({
      timeout: timeoutMs,
    });
  }

  // ---------------------------------------------------------------------------
  // Popover / sidebar
  // ---------------------------------------------------------------------------

  async openUserDropdown() {
    await this.userDropdownTrigger.click();
  }

  async expectCustomHelpLinkVisible(label: string, url: string) {
    await expect(this.customHelpLinkItem).toBeVisible({ timeout: 5_000 });
    await expect(this.customHelpLinkItem).toContainText(label);
    // LineItemButton with href renders an <a> with that href under the hood
    await expect(
      this.customHelpLinkItem.locator(`a[href="${url}"]`)
    ).toHaveCount(1);
  }

  async expectCustomHelpLinkContainsText(text: string) {
    await expect(this.customHelpLinkItem).toBeVisible({ timeout: 5_000 });
    await expect(this.customHelpLinkItem).toContainText(text);
  }

  async expectPoweredByOnyxVisible() {
    await expect(this.page.getByText("Powered by Onyx").first()).toBeVisible({
      timeout: 5_000,
    });
  }

  async expectPoweredByOnyxAbsent() {
    await expect(this.page.getByText("Powered by Onyx")).toHaveCount(0, {
      timeout: 5_000,
    });
  }

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  async expectValidationMessage(text: string) {
    await expect(this.page.getByText(text)).toBeVisible({ timeout: 5_000 });
  }
}
