import { expect, type Locator, type Page } from "@playwright/test";

export class AdminUsagePage {
  readonly page: Page;
  readonly usageRows: Locator;

  constructor(page: Page) {
    this.page = page;
    this.usageRows = page.locator('tr[aria-label^="View usage details for "]');
  }

  async goto(): Promise<void> {
    await this.page.goto("/admin/performance/usage");
    await expect(this.usageRows.first()).toBeVisible({ timeout: 15_000 });
  }

  async expectUser(email: string): Promise<void> {
    const row = this.page.getByRole("row", {
      name: `View usage details for ${email}`,
    });
    await expect(row).toBeVisible();
  }
}
