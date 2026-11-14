/**
 * Page Object Model for the Craft Skills library (/craft/v1/skills) and the
 * skill dialog it opens.
 */

import { type Locator, type Page, expect } from "@playwright/test";

const SKILLS_PATH = "/craft/v1/skills";

export class SkillsLibraryPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(): Promise<void> {
    await this.page.goto(SKILLS_PATH);
    const intro = this.page
      .getByRole("dialog")
      .filter({ hasText: "Meet Craft" });
    const introAppeared = await intro
      .waitFor({ state: "visible", timeout: 3000 })
      .then(() => true)
      .catch(() => false);
    if (introAppeared) {
      await this.page.keyboard.press("Escape");
      await expect(intro).toBeHidden();
    }
    await expect(this.page.getByTestId("SkillsPage/container")).toBeVisible();
  }

  card(name: string): Locator {
    return this.page.getByTestId("SkillCard").filter({
      has: this.page.getByRole("button", { name, exact: true }),
    });
  }

  get dialog(): Locator {
    return this.page.getByRole("dialog");
  }

  async openSkill(name: string): Promise<void> {
    await this.page
      .getByTestId("SkillsPage/container")
      .getByRole("button", { name, exact: true })
      .click();
    await expect(this.dialog).toBeVisible();
  }

  async openVersionsTab(): Promise<void> {
    await this.dialog.getByRole("tab", { name: "Versions" }).click();
    await expect(
      this.dialog.getByRole("table", { name: "Skill versions" })
    ).toBeVisible();
  }

  versionRow(versionNumber: number): Locator {
    return this.dialog.getByRole("row", {
      name: `Preview version ${versionNumber}`,
    });
  }

  async expectCardUnpublishedChanges(
    name: string,
    shown: boolean
  ): Promise<void> {
    const badge = this.card(name).getByText("Unpublished changes", {
      exact: true,
    });
    if (shown) await expect(badge).toBeVisible();
    else await expect(badge).toHaveCount(0);
  }

  get publishUpdateButton(): Locator {
    return this.dialog.getByRole("button", { name: "Publish update" });
  }

  async publishUpdate(): Promise<void> {
    await this.publishUpdateButton.click();
  }

  async expectVersionStatus(
    versionNumber: number,
    status: string
  ): Promise<void> {
    await expect(
      this.versionRow(versionNumber).getByText(status, { exact: true })
    ).toBeVisible();
  }

  async expectToast(text: string): Promise<void> {
    await expect(this.page.getByText(text, { exact: true })).toBeVisible();
  }

  async closeDialog(): Promise<void> {
    await this.page.keyboard.press("Escape");
    await expect(this.dialog).toBeHidden();
  }
}
