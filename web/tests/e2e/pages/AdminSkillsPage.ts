import { expect, type Page } from "@playwright/test";
import { SkillUploadDialog } from "@tests/e2e/pages/SkillUploadDialog";

export class AdminSkillsPage {
  constructor(readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/admin/skills");
  }

  async openUpload(): Promise<SkillUploadDialog> {
    await this.page
      .getByRole("button", { name: "Create skill", exact: true })
      .click();
    await this.page.getByText("Upload a skill", { exact: true }).click();
    const upload = new SkillUploadDialog(this.page);
    await upload.expectVisible();
    return upload;
  }

  async expectSkillVisible(name: string): Promise<void> {
    await expect(
      this.page.getByText(name, { exact: true }).first()
    ).toBeVisible();
  }

  async expectSkillAbsent(name: string): Promise<void> {
    await expect(this.page.getByText(name, { exact: true })).toHaveCount(0);
  }
}
