import { Locator, Page } from "@playwright/test";

/**
 * The "files in this project" section of the project view: the file cards
 * plus the "Add Files" affordance above them.
 *
 * The file rows are Opal `AttachmentItemButton`s. The title is located by
 * its visible text; the icon tile has no testid, role or text, so its Opal
 * class is the documented last-resort locator.
 */
export class ProjectFilesSection {
  constructor(readonly page: Page) {}

  get section(): Locator {
    return this.page
      .locator("div")
      .filter({ has: this.page.getByRole("button", { name: "Add Files" }) })
      .filter({ hasText: "Chats in this project can access these files." })
      .first();
  }

  /** A file card's title, by the file's visible name. */
  fileTitle(fileName: string): Locator {
    return this.section.getByText(fileName).first();
  }

  /** The first file card's icon tile. */
  get attachmentTile(): Locator {
    return this.section.locator(".opal-attachment-item-button-tile").first();
  }
}
