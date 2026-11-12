/**
 * Page Object Model for Admin Panel → Craft → Preferences
 * (/admin/craft/preferences): the Skill Publishing setting.
 */

import { type Page, expect } from "@playwright/test";

export type PublishingLabel = "Open" | "Requires review" | "Off";

export class AdminCraftPreferencesPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(): Promise<void> {
    await this.page.goto("/admin/craft/preferences");
    await expect(this.page.getByText("Skill Publishing")).toBeVisible();
  }

  async setPublishing(label: PublishingLabel): Promise<void> {
    await this.page.getByRole("combobox", { name: "Skill Publishing" }).click();
    await this.page.getByRole("option", { name: label }).click();
    await expect(
      this.page.getByText("Publishing setting saved.", { exact: true })
    ).toBeVisible();
  }
}
