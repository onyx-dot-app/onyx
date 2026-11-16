/**
 * Page Object Model for Admin Panel → Skills (/admin/skills): the publish
 * requests list, the skill cards and their sharing dialog.
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

  async openReview(name: string): Promise<void> {
    await this.page.getByRole("button", { name: `Review ${name}` }).click();
    await expect(this.page.getByRole("dialog")).toBeVisible();
  }

  async expectReviewContent(text: string): Promise<void> {
    await expect(
      this.page.getByRole("dialog").getByText(text, { exact: true })
    ).toBeVisible();
  }

  async approveInReview(): Promise<void> {
    await this.page
      .getByRole("dialog")
      .getByRole("button", { name: "Approve", exact: true })
      .click();
  }

  async expectNoRequest(name: string): Promise<void> {
    await expect(
      this.page.getByRole("button", { name: `Review ${name}` })
    ).toHaveCount(0);
  }

  card(name: string): Locator {
    return this.page.getByTestId("SkillCard").filter({
      has: this.page.getByRole("button", { name, exact: true }),
    });
  }

  async openSharing(name: string): Promise<void> {
    await this.card(name).getByRole("button", { name: "Edit sharing" }).click();
    await expect(this.page.getByRole("dialog")).toBeVisible();
  }

  /** Adds a group in Group Access and gives it a policy, then saves. */
  async setGroupPolicy(group: string, policy: RegExp): Promise<void> {
    await this.page
      .getByRole("dialog")
      .getByRole("combobox", { name: "Add a group" })
      .click();
    await this.page.getByRole("option", { name: group }).click();
    await this.page
      .getByRole("dialog")
      .getByRole("combobox", { name: `Setting for ${group}` })
      .click();
    await this.page.getByRole("option", { name: policy }).click();
    await this.page
      .getByRole("dialog")
      .getByRole("button", { name: "Save" })
      .click();
    await expect(this.page.getByRole("dialog")).toBeHidden();
  }

  async expectCardText(name: string, text: string): Promise<void> {
    await expect(this.card(name).getByText(text)).toBeVisible();
  }

  async filterByGroup(group: string): Promise<void> {
    await this.page.getByRole("combobox", { name: "Filter by group" }).click();
    await this.page.getByRole("option", { name: group }).click();
  }

  async expectCardShown(name: string, shown: boolean): Promise<void> {
    if (shown) await expect(this.card(name)).toBeVisible();
    else await expect(this.card(name)).toHaveCount(0);
  }

  async expectToast(text: string): Promise<void> {
    await expect(this.page.getByText(text, { exact: true })).toBeVisible();
  }
}
