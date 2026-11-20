/**
 * Page Object Model for the Service Status admin page (/admin/service-status).
 */

import { type Locator, type Page, expect } from "@playwright/test";

export class AdminServiceStatusPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(): Promise<void> {
    await this.page.goto("/admin/service-status");
    await expect(this.issuesPanel).toBeVisible();
  }

  get nodes(): Locator {
    return this.page.getByTestId("service-status-node");
  }

  get indexes(): Locator {
    return this.page.getByTestId("service-status-index");
  }

  get issuesPanel(): Locator {
    return this.page.getByTestId("service-status-issues");
  }

  async refresh(): Promise<void> {
    await this.page.getByRole("button", { name: "Refresh" }).click();
  }
}
