/**
 * Page Object Model for the Account settings tab (/app/settings/account).
 *
 * Covers loading the tab, including from an old settings path that
 * redirects here.
 */

import { expect, type Locator, type Page } from "@playwright/test";

const ACCOUNT_PATH = "/app/settings/account";

export class SettingsAccountPage {
  readonly fullNameRow: Locator;

  constructor(readonly page: Page) {
    this.fullNameRow = page.getByText("Full Name", { exact: true });
  }

  /**
   * Load `path` with a page load and wait until it shows this tab. Pass an
   * old settings path to follow its redirect.
   */
  async load(path: string = ACCOUNT_PATH): Promise<void> {
    await this.page.goto(path);
    await expect(this.page).toHaveURL(new RegExp(`${ACCOUNT_PATH}$`));
    await expect(this.fullNameRow).toBeVisible();
  }
}
