import { expect, type Page } from "@playwright/test";
import { CraftOutputsPage } from "@tests/e2e/pages/CraftOutputsPage";

export class CraftDocumentPreviewPage {
  readonly outputs: CraftOutputsPage;
  constructor(private readonly page: Page) {
    this.outputs = new CraftOutputsPage(page);
  }
  async openFile(path: string) {
    await this.outputs.panel
      .getByRole("button", { name: path, exact: true })
      .click();
  }
  async selectTab(name: string) {
    await this.page.getByRole("tab", { name, exact: true }).click();
  }
  async expectPdfPage(page: 1 | 2) {
    const preview = this.page.getByRole("region", {
      name: `Page ${page} preview`,
      exact: true,
    });
    await expect(preview).toBeVisible();
    await expect(
      preview.getByText(page === 1 ? "Page one content" : "Page two content", {
        exact: true,
      })
    ).toBeVisible();
    // React-PDF exposes no canvas role; text and canvas together verify the real PDF.js rendering pipeline.
    await expect(preview.locator("canvas")).toBeVisible();
    await expect(
      this.page.getByRole("toolbar", { name: "PDF controls", exact: true })
    ).toContainText(`${page} / 2`);
  }
  async nextPdfPage() {
    await this.page
      .getByRole("button", { name: "Next page", exact: true })
      .click();
  }
  async selectPdfThumbnail(page: number) {
    await this.page
      .getByRole("button", { name: `Go to page ${page}`, exact: true })
      .click();
  }
  async setPdfZoom(value: string) {
    await this.page.getByRole("button", { name: "Zoom", exact: true }).click();
    await this.page.getByRole("option", { name: value, exact: true }).click();
  }
  async expectPdfZoom(value: string) {
    await expect(
      this.page.getByRole("button", { name: "Zoom", exact: true })
    ).toContainText(value);
  }
  async resizePdfThumbnails() {
    const divider = this.page.getByRole("separator", {
      name: "Resize page thumbnails",
      exact: true,
    });
    await expect(divider).toHaveAttribute("aria-valuenow", "144");
    await divider.focus();
    await divider.press("ArrowRight");
    await expect(divider).toHaveAttribute("aria-valuenow", "154");
  }
  async togglePdfThumbnails(visible: boolean) {
    await this.page
      .getByRole("button", { name: "Toggle page thumbnails", exact: true })
      .click();
    const divider = this.page.getByRole("separator", {
      name: "Resize page thumbnails",
      exact: true,
    });
    if (visible) await expect(divider).toBeVisible();
    else await expect(divider).toBeHidden();
  }
  async expectPresentationSlide(slide: number) {
    const toolbar = this.page.getByRole("toolbar", {
      name: "Presentation controls",
      exact: true,
    });
    await expect(toolbar).toContainText(`Slide ${slide} of 2`);
    const image = this.page.getByRole("img", {
      name: `Slide ${slide} of 2`,
      exact: true,
    });
    await expect(image).toBeVisible();
    await expect(image).toHaveJSProperty("complete", true);
    await expect(image).not.toHaveJSProperty("naturalWidth", 0);
  }
  async nextPresentationSlide() {
    await this.page
      .getByRole("button", { name: "Next slide", exact: true })
      .click();
  }
  async resizePresentationThumbnails() {
    const divider = this.page.getByRole("separator", {
      name: "Resize slide thumbnails",
      exact: true,
    });
    await expect(divider).toHaveAttribute("aria-valuenow", "112");
    await divider.focus();
    await divider.press("ArrowRight");
    await expect(divider).toHaveAttribute("aria-valuenow", "122");
  }
}
