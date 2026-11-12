/**
 * Page Object Model for the Discord bot admin page (/admin/discord-bot),
 * which lists the bot's guilds.
 *
 * Currently covers the page's loading state and title.
 */

import { type Page, type Locator } from "@playwright/test";

export class DiscordBotPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  /**
   * The page body's loader (OnyxLoader, role="status"). Scoped to the body:
   * the admin sidebar's loader can show at the same time.
   */
  get loader(): Locator {
    return this.page
      .locator("#page-wrapper-scroll-container")
      .getByRole("status");
  }

  /** The "Discord Integration" page title. */
  get title(): Locator {
    return this.page
      .locator('[aria-label="admin-page-title"]')
      .getByText("Discord Integration");
  }
}
