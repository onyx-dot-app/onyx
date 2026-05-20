/**
 * Page Object Model for the Admin Appearance / Theme page (/admin/theme).
 *
 * Encapsulates locators and interactions for the custom help link and
 * hide-onyx-branding controls so specs stay declarative. Existing tests in
 * `appearance_theme_settings.spec.ts` still use inline locators; new tests
 * should drive the page through this class.
 */

import {
  expect,
  type Locator,
  type Page,
  type Response,
} from "@playwright/test";

const ENTERPRISE_SETTINGS_PUT = (r: Response) =>
  r.url().includes("/api/admin/enterprise-settings") &&
  r.request().method() === "PUT";

/**
 * SWR revalidation `GET /api/enterprise-settings` fired by `mutate()` after
 * a successful save. The popover renders straight from this SWR cache, so
 * waiting for this GET (in addition to the PUT) guarantees the sidebar
 * popover reflects the new values before we assert on them.
 */
const ENTERPRISE_SETTINGS_GET = (r: Response) => {
  if (r.request().method() !== "GET") return false;
  const pathname = new URL(r.url()).pathname;
  return pathname === "/api/enterprise-settings";
};

export class AppearanceThemePage {
  readonly page: Page;

  // Form inputs
  readonly applicationNameInput: Locator;
  readonly customHelpLinkUrlInput: Locator;
  readonly customHelpLinkLabelInput: Locator;
  readonly hideBrandingToggle: Locator;
  readonly saveButton: Locator;

  // Sidebar / popover
  readonly userDropdownTrigger: Locator;

  constructor(page: Page) {
    this.page = page;
    this.applicationNameInput = page.locator(
      '[data-label="application-name-input"]'
    );
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
  }

  /**
   * The custom help link is rendered by Opal's `LineItemButton`, which
   * forwards `href` to an underlying `<a>` but drops arbitrary props such
   * as `data-testid` somewhere in the `LineItemButton → ContentAction →
   * Content` chain. Locating by `href` is reliable and reflects what the
   * user actually clicks on.
   */
  customHelpLinkAnchor(url: string): Locator {
    return this.page.locator(`a[href="${url}"]`);
  }

  // ---------------------------------------------------------------------------
  // Form interactions
  // ---------------------------------------------------------------------------

  async setApplicationName(name: string) {
    await this.applicationNameInput.fill(name);
  }

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
   * Click "Apply Changes" and wait for both the PUT and the subsequent SWR
   * revalidation GET. Both promises MUST be armed before the click — a
   * post-click `waitForResponse` can miss fast responses and flake.
   *
   * Returns the PUT response so callers can assert on the status code.
   */
  async saveAndWaitForPut(timeoutMs = 10_000): Promise<Response> {
    const putPromise = this.page.waitForResponse(ENTERPRISE_SETTINGS_PUT, {
      timeout: timeoutMs,
    });
    const getPromise = this.page.waitForResponse(ENTERPRISE_SETTINGS_GET, {
      timeout: timeoutMs,
    });
    await expect(this.saveButton).toBeEnabled();
    await this.saveButton.click();
    const [putResponse] = await Promise.all([putPromise, getPromise]);
    return putResponse;
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

  /**
   * Reload + wait for the admin form to be back. Use after a save to clear
   * any SWR cache / React render races — once the page comes back up the
   * sidebar reads enterprise settings fresh from the server.
   */
  async reloadAndWaitForForm(timeoutMs = 10_000) {
    await this.page.reload();
    await expect(
      this.page.locator('[data-label="application-name-input"]')
    ).toBeVisible({ timeout: timeoutMs });
  }

  async expectCustomHelpLinkVisible(label: string, url: string) {
    const link = this.customHelpLinkAnchor(url);
    await expect(link).toBeVisible({ timeout: 5_000 });
    await expect(link).toContainText(label);
  }

  async expectCustomHelpLinkContainsText(url: string, text: string) {
    const link = this.customHelpLinkAnchor(url);
    await expect(link).toBeVisible({ timeout: 5_000 });
    await expect(link).toContainText(text);
  }

  /**
   * Locator for the Logo's tagline, scoped exactly so it doesn't also match
   * the toggle's helper text on the same page ("Remove 'powered by Onyx'
   * and other Onyx branding..."). `getByText` is case-insensitive +
   * substring by default; `exact: true` makes it strict equality on the
   * element's full text content.
   */
  private get poweredByOnyxTagline(): Locator {
    return this.page.getByText("Powered by Onyx", { exact: true });
  }

  async expectPoweredByOnyxVisible() {
    await expect(this.poweredByOnyxTagline).toBeVisible({ timeout: 5_000 });
  }

  async expectPoweredByOnyxAbsent() {
    await expect(this.poweredByOnyxTagline).toHaveCount(0, { timeout: 5_000 });
  }

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  async expectValidationMessage(text: string) {
    await expect(this.page.getByText(text)).toBeVisible({ timeout: 5_000 });
  }
}
