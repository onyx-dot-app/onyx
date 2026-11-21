import { expect, type Locator, type Page } from "@playwright/test";

/** The modal that previews a file linked from a chat answer. */
export class FilePreviewModalPage {
  private readonly modal: Locator;

  constructor(private readonly page: Page) {
    this.modal = page.getByRole("dialog");
  }

  /** Checks the icon-only download link and the tooltip that names it. */
  async expectDownloadLinkWithTooltip(): Promise<void> {
    const link = this.modal.getByRole("link", { name: "Download" });
    await expect(link).toBeVisible();
    await link.hover();
    await expect(
      this.page.getByText("Download", { exact: true }).first()
    ).toBeVisible({ timeout: 3000 });
  }
}
