import { expect, type Locator, type Page } from "@playwright/test";

export class SkillUploadDialog {
  readonly dialog: Locator;

  constructor(readonly page: Page) {
    this.dialog = page.getByRole("dialog").filter({ hasText: "Upload skill" });
  }

  async expectVisible(): Promise<void> {
    await expect(this.dialog).toBeVisible();
  }

  async expectControlsInsideViewport(): Promise<void> {
    await expect(this.dialog).toBeInViewport({ ratio: 1 });
    await expect(
      this.dialog.getByRole("button", { name: "Close", exact: true })
    ).toBeInViewport({ ratio: 1 });
    await expect(
      this.dialog.getByRole("button", { name: "Cancel", exact: true })
    ).toBeInViewport({ ratio: 1 });
  }

  async close(): Promise<void> {
    await this.dialog
      .getByRole("button", { name: "Close", exact: true })
      .click();
    await expect(this.dialog).toBeHidden();
  }

  async selectFiles(
    files: Parameters<Locator["setInputFiles"]>[0]
  ): Promise<void> {
    await this.dialog
      .getByLabel("file upload", { exact: true })
      .setInputFiles(files);
  }

  async expectMessage(text: string | RegExp): Promise<void> {
    await expect(this.dialog.getByText(text, { exact: true })).toBeVisible();
  }

  async import(): Promise<void> {
    const response = this.page.waitForResponse(
      (result) =>
        result.url().endsWith("/api/skills/custom/batch") &&
        result.request().method() === "POST"
    );
    await this.dialog.getByRole("button", { name: /Import/ }).click();
    expect((await response).status()).toBe(200);
  }

  async done(): Promise<void> {
    await this.dialog.getByRole("button", { name: "Done" }).click();
    await expect(this.dialog).toBeHidden();
  }
}
