import { expect, type Page } from "@playwright/test";

export class DropdownStoryPage {
  constructor(private readonly page: Page) {}

  async open() {
    await this.page.goto(
      "/iframe.html?id=components-dropdown--viewport-bounds&viewMode=story",
      { waitUntil: "domcontentloaded" }
    );
    await this.page.getByRole("button", { name: "Choose an option" }).click();
  }

  async expectAboveTrigger() {
    const list = this.page.getByRole("listbox", { name: "Options" });
    const trigger = this.page.getByRole("button", { name: "Choose an option" });
    await expect
      .poll(async () => {
        const listBounds = await list.boundingBox();
        const triggerBounds = await trigger.boundingBox();
        return listBounds && triggerBounds
          ? listBounds.y + listBounds.height <= triggerBounds.y
          : false;
      })
      .toBe(true);
  }

  async scrollToLastOption() {
    const list = this.page.getByRole("listbox", { name: "Options" });
    const last = this.page.getByRole("option", {
      name: "Option 50",
      exact: true,
    });
    await expect(last).not.toBeInViewport();
    await list.hover();
    await this.page.mouse.wheel(0, 10000);
    await expect(last).toBeInViewport({ ratio: 1 });
    await expect(this.page.getByPlaceholder("Search options")).toBeInViewport({
      ratio: 1,
    });
    await expect(
      this.page.getByRole("option", { name: "Option 1", exact: true })
    ).not.toBeInViewport();
    await last.click();
    await expect(list).toBeHidden();
  }
}
