/**
 * Page Object Model for the Appearance settings page
 * (/app/settings/appearance).
 *
 * Covers the Full-Width Chat switch.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class SettingsAppearancePage {
  readonly page: Page;
  readonly fullWidthChatSwitch: Locator;

  constructor(page: Page) {
    this.page = page;
    this.fullWidthChatSwitch = page.getByRole("switch", {
      name: "Full-Width Chat",
    });
  }

  async goto(): Promise<void> {
    await this.page.goto("/app/settings/appearance");
    await expect(this.fullWidthChatSwitch).toBeVisible();
  }

  async setFullWidthChat(enabled: boolean): Promise<void> {
    await this.fullWidthChatSwitch.setChecked(enabled);
    await expect(this.fullWidthChatSwitch).toBeChecked({ checked: enabled });
  }
}
