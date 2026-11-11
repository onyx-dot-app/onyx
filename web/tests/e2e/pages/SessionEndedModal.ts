import { type Locator, type Page, expect } from "@playwright/test";

/** The "You Have Been Logged Out" modal shown when the session ends. */
export class SessionEndedModal {
  readonly page: Page;
  readonly title: Locator;
  readonly message: Locator;

  constructor(page: Page) {
    this.page = page;
    this.title = page.getByText("You Have Been Logged Out");
    this.message = page.getByText(
      "This session was signed out. Please log in again"
    );
  }

  async expectVisible(): Promise<void> {
    await expect(this.title).toBeVisible();
    await expect(this.message).toBeVisible();
  }
}
