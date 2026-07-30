import { expect, type Locator, type Page } from "@playwright/test";

const RESET_ENDPOINT = "/api/admin/usage/reset";

export class AdminUsagePage {
  readonly page: Page;
  readonly usageRows: Locator;

  constructor(page: Page) {
    this.page = page;
    this.usageRows = page.locator('[data-testid^="usage-row-"]');
  }

  async goto(): Promise<void> {
    await this.page.goto("/admin/performance/usage");
    await expect(this.usageRows.first()).toBeVisible({ timeout: 15_000 });
  }

  async resetFirstUser(): Promise<void> {
    const row = this.usageRows.first();
    const responsePromise = this.page.waitForResponse(
      (response) =>
        response.url().includes(RESET_ENDPOINT) &&
        response.request().method() === "POST"
    );

    await row.getByRole("button", { name: "Reset" }).click();
    expect((await responsePromise).ok()).toBeTruthy();
    await expect(this.page.getByText(/reset usage for/i)).toBeVisible({
      timeout: 10_000,
    });
  }
}
