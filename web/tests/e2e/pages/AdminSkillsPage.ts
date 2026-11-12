/**
 * Page Object Model for Admin Panel → Skills (/admin/skills): the publish
 * requests list.
 */

import { type Locator, type Page, expect } from "@playwright/test";

export class AdminSkillsPage {
  readonly page: Page;
  readonly requests: Locator;

  constructor(page: Page) {
    this.page = page;
    this.requests = page.getByRole("table", { name: "Publish Requests" });
  }

  async goto(): Promise<void> {
    await this.page.goto("/admin/skills");
    await expect(this.page.getByTestId("SkillsPage/container")).toBeVisible();
  }

  async expectRequest(name: string, kind: string): Promise<void> {
    const row = this.requests.getByRole("row").filter({ hasText: name });
    await expect(row).toBeVisible();
    await expect(row.getByText(kind, { exact: true })).toBeVisible();
  }

  async approve(name: string): Promise<void> {
    await this.page.getByRole("button", { name: `Approve ${name}` }).click();
  }

  async expectNoRequest(name: string): Promise<void> {
    await expect(
      this.page.getByRole("button", { name: `Approve ${name}` })
    ).toHaveCount(0);
  }

  async expectToast(text: string): Promise<void> {
    await expect(this.page.getByText(text, { exact: true })).toBeVisible();
  }
}
