import { type Locator, type Page, expect } from "@playwright/test";

/** The document `<head>` that the root layout renders on every page. */
export class DocumentHead {
  readonly page: Page;
  readonly viewportMeta: Locator;

  constructor(page: Page) {
    this.page = page;
    this.viewportMeta = page.locator('head meta[name="viewport"]');
  }

  /** Checks that one viewport tag exists and that it lets the user zoom. */
  async expectZoomAllowed(): Promise<void> {
    await expect(this.viewportMeta).toHaveCount(1);
    await expect(this.viewportMeta).toHaveAttribute(
      "content",
      /width=device-width/
    );
    await expect(this.viewportMeta).not.toHaveAttribute(
      "content",
      /user-scalable\s*=\s*(0|no)|maximum-scale/
    );
  }

  async expectTitle(title: string | RegExp): Promise<void> {
    await expect(this.page).toHaveTitle(title);
  }
}
