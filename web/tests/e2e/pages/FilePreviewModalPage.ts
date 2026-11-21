import { expect, type Locator, type Page } from "@playwright/test";

/** The modal that previews a file linked from a chat answer. */
export class FilePreviewModalPage {
  private readonly modal: Locator;
  private readonly pdfControls: Locator;

  constructor(private readonly page: Page) {
    this.modal = page.getByRole("dialog");
    this.pdfControls = this.modal.getByRole("toolbar", {
      name: "PDF controls",
      exact: true,
    });
  }

  /** Clicks a file link in the last AI message and waits for the modal. */
  async openFromLastAnswer(fileName: string): Promise<void> {
    const link = this.page
      .getByTestId("onyx-ai-message")
      .last()
      .getByRole("button", { name: fileName });
    await expect(link).toBeVisible({ timeout: 5000 });
    await link.click();
    await expect(this.modal).toBeVisible({ timeout: 5000 });
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

  /** Checks the file name in the header and the download link. */
  async expectFileWithDownload(fileName: string): Promise<void> {
    await expect(this.modal.getByText(fileName)).toBeVisible();
    await expect(this.modal.locator("a[download]")).toBeVisible();
  }

  /** Checks the message for a file type that has no preview. */
  async expectUnsupported(): Promise<void> {
    await expect(
      this.modal.getByText(
        "Preview for this file type is not currently supported"
      )
    ).toBeVisible();
  }

  /**
   * Checks that the Word document's pages render, and contain `text` when
   * given, with neither the load nor the render error. The pages render in a
   * shadow root, which Playwright's locators pierce.
   */
  async expectDocxPages(text?: string): Promise<void> {
    const pages = this.modal.locator("section.docx");
    await expect(pages.first()).toBeVisible({ timeout: 10000 });
    if (text) await expect(pages).toContainText([text]);
    await expect(this.modal.getByText("Unable to load preview")).toHaveCount(0);
    await expect(this.modal.getByText("Cannot preview this file")).toHaveCount(
      0
    );
  }

  /** Checks that the PDF shows `page` of `pageCount` and draws that page. */
  async expectPdfPage(page: number, pageCount: number): Promise<void> {
    await expect(this.pdfControls).toContainText(`${page} / ${pageCount}`, {
      timeout: 10000,
    });
    await expect(
      this.modal
        .getByRole("region", { name: `Page ${page} preview`, exact: true })
        .locator("canvas")
    ).toBeVisible();
  }

  async nextPdfPage(): Promise<void> {
    await this.pdfControls
      .getByRole("button", { name: "Next page", exact: true })
      .click();
  }

  async expectLastPdfPage(): Promise<void> {
    await expect(
      this.pdfControls.getByRole("button", { name: "Next page", exact: true })
    ).toBeDisabled();
  }
}
