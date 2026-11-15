/**
 * Page Object Model for a Discord guild's detail page
 * (/admin/discord-bot/[guild-id]).
 *
 * Currently covers the Default Agent select. Its trigger is Opal's
 * read-only combobox input, named by its placeholder.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class DiscordGuildPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  /** The Default Agent section heading. */
  get defaultAgentHeading(): Locator {
    return this.page.locator("text=Default Agent").first();
  }

  /** The Default Agent select trigger. */
  get defaultAgentSelect(): Locator {
    return this.page.getByRole("combobox", { name: "Select agent" });
  }

  /** Open the Default Agent select and assert it offers at least one agent. */
  async expectDefaultAgentOptions(): Promise<void> {
    await this.defaultAgentSelect.click();
    await expect(this.page.getByRole("option").first()).toBeVisible({
      timeout: 5000,
    });
  }
}
