import { expect, type Locator, type Page } from "@playwright/test";

/**
 * The page of an artifact link, `/app/artifacts/<artifact_id>[/v<N>]`, opened
 * outside a chat. It goes to the owning chat or its shared view, or shows the
 * file alone.
 */
export class ArtifactLinkPage {
  readonly page: Page;
  readonly download: Locator;

  constructor(page: Page) {
    this.page = page;
    // The page header's download; the preview has its own.
    this.download = page
      .getByTestId("artifact-link-header")
      .getByRole("link", { name: "Download" });
  }

  /** Opens `link` and resolves with the status of its metadata request. */
  async goto(link: string): Promise<number> {
    const metadata = this.page.waitForResponse((response) =>
      response.url().includes("/api/chat/artifacts/")
    );
    await this.page.goto(link);
    return (await metadata).status();
  }

  /** The preview of the file alone, by its title or name. */
  filePreview(title: string): Locator {
    return this.page.getByRole("region", { name: `Preview of ${title}` });
  }

  /** The link shows that its file is not available, and no preview. */
  async expectNotFound(link: string, title: string): Promise<void> {
    await expect(this.page).toHaveURL((url) => url.pathname === link);
    await expect(
      this.page.getByText("This file is not available")
    ).toBeVisible();
    await expect(this.filePreview(title)).toHaveCount(0);
  }
}
