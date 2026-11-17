import { expect, type Locator, type Page } from "@playwright/test";
import { CraftOutputsPage } from "@tests/e2e/pages/CraftOutputsPage";

export class CraftSkillNoticePage {
  readonly outputs: CraftOutputsPage;
  readonly title: Locator;

  constructor(private readonly page: Page) {
    this.outputs = new CraftOutputsPage(page);
    this.title = page.getByText(/skills? did not load$/);
  }

  async expectNotice(title: string, skillName: string): Promise<void> {
    await expect(this.page.getByText(title, { exact: true })).toBeVisible();
    await expect(this.page.getByText(new RegExp(skillName))).toBeVisible();
  }

  async dismiss(): Promise<void> {
    await this.page.getByRole("button", { name: "Dismiss" }).click();
    await expect(this.title).toHaveCount(0);
  }
}
