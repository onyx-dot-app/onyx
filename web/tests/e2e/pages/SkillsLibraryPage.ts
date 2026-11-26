/**
 * Page Object Model for the Skills tab of Customize (/app/customize/skills)
 * and the page of one skill.
 */

import { type Locator, type Page, expect } from "@playwright/test";

const SKILLS_PATH = "/app/customize/skills";

export class SkillsLibraryPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(): Promise<void> {
    await this.page.goto(SKILLS_PATH);
    await expect(
      this.page.getByRole("tab", { name: "Skills", exact: true })
    ).toHaveAttribute("aria-selected", "true");
  }

  card(name: string): Locator {
    return this.page.getByRole("button", { name: `Open ${name}`, exact: true });
  }

  async openSkill(name: string): Promise<void> {
    await this.card(name).click();
    await expect(this.page).toHaveURL(
      /\/app\/customize\/skills\/[0-9a-f-]{36}/
    );
  }

  /** Opens the Contents tab of a skill in edit mode. */
  async openContentsEditor(skillId: string): Promise<void> {
    await this.page.goto(`${SKILLS_PATH}/${skillId}?edit=1`);
    await expect(this.skillMdEditor).toBeVisible();
  }

  get skillMdEditor(): Locator {
    return this.page.getByRole("textbox", { name: "SKILL.md", exact: true });
  }

  /** Opens the create page, where SKILL.md is the editor's text. */
  async openCreatePage(): Promise<void> {
    await this.page.goto(`${SKILLS_PATH}/new`);
    await expect(this.skillMdEditor).toBeVisible();
  }

  /** Adds files through the editor's Add File picker. */
  async addSkillFiles(
    files: Parameters<Locator["setInputFiles"]>[0]
  ): Promise<void> {
    await this.page.getByLabel("Add skill files").setInputFiles(files);
  }

  /** Confirms the dialog that replaces the editor with a SKILL.md bundle. */
  async confirmSkillImport(): Promise<void> {
    const dialog = this.page
      .getByRole("dialog")
      .filter({ hasText: "Import this skill?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Import skill" }).click();
    await expect(dialog).toBeHidden();
  }

  /** Replaces the text of SKILL.md and saves a version. */
  async saveSkillMd(text: string): Promise<void> {
    await this.skillMdEditor.fill(text);
    await this.page
      .getByRole("button", { name: "Save Version", exact: true })
      .click();
    await expect(this.page).toHaveURL(/\?tab=contents$/);
    await expect(this.skillMdEditor).toHaveCount(0);
  }

  async openVersionsTab(): Promise<void> {
    await this.page.getByRole("tab", { name: "Versions" }).click();
    await expect(
      this.page.getByRole("table", { name: "Skill versions" })
    ).toBeVisible();
  }

  versionRow(versionNumber: number): Locator {
    return this.page.getByRole("row", {
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
    return this.page.getByRole("button", { name: "Publish update" });
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

  async backToList(): Promise<void> {
    await this.page.getByRole("link", { name: "Skills", exact: true }).click();
    await expect(this.page).toHaveURL(/\/app\/customize\/skills$/);
  }
}
