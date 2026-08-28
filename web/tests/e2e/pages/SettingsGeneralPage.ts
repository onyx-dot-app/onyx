/**
 * Page Object Model for the General settings page (/app/settings/general).
 *
 * Currently covers the language picker in the Appearance section. The picker
 * lists languages by endonym (English, Español, ...), so its trigger and
 * option locators are locale-independent and safe to use in any UI language.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class SettingsGeneralPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  /** Navigate to the page and wait for it to finish loading. */
  async goto(): Promise<void> {
    await this.page.goto("/app/settings/general");
    await this.page.waitForLoadState("networkidle");
  }

  /** Reload the page and wait for it to finish loading. */
  async reload(): Promise<void> {
    await this.page.reload();
    await this.page.waitForLoadState("networkidle");
  }

  /** The language select trigger, located by the endonym it displays. */
  languageSelect(currentEndonym: string): Locator {
    return this.page.getByRole("combobox").filter({ hasText: currentEndonym });
  }

  /** Open the language select and choose a language by its endonym. */
  async switchLanguage(
    currentEndonym: string,
    targetEndonym: string
  ): Promise<void> {
    const select = this.languageSelect(currentEndonym);
    await expect(select).toBeVisible();
    await select.click();
    await this.page
      .getByRole("option", { name: targetEndonym, exact: true })
      .click();
  }

  /** Assert the document language and a marker string for the active locale. */
  async expectLocale(lang: string, markerText: string): Promise<void> {
    await expect(this.page.locator("html")).toHaveAttribute("lang", lang);
    await expect(this.page.getByText(markerText).first()).toBeVisible();
  }
}
