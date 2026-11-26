import { expect, type Locator, type Page } from "@playwright/test";

/** The page of one indexed document, `/app/document?id=<document id>`. */
export class DocumentViewPage {
  readonly page: Page;
  readonly notFound: Locator;

  constructor(page: Page) {
    this.page = page;
    this.notFound = page.getByText(
      "Document not found or you do not have access"
    );
  }

  async gotoWithoutId(): Promise<void> {
    await this.page.goto("/app/document");
  }

  async goto(documentId: string): Promise<void> {
    await this.page.goto(`/app/document?id=${encodeURIComponent(documentId)}`);
  }

  async expectDocument(title: string, text: string): Promise<void> {
    await expect(this.page.getByText(title, { exact: true })).toBeVisible();
    await expect(this.page.getByText(text)).toBeVisible();
    await expect(
      this.page.getByRole("link", { name: "Open source" })
    ).toHaveCount(0);
  }

  async expectNotFound(): Promise<void> {
    await expect(this.notFound).toBeVisible();
  }
}
