import { type Locator, type Page, expect } from "@playwright/test";

export class ToolsPopover {
  readonly page: Page;
  readonly toggle: Locator;
  readonly popover: Locator;

  constructor(page: Page) {
    this.page = page;
    this.toggle = page.getByTestId("action-management-toggle");
    this.popover = page.getByTestId("tool-options");
  }

  async open(): Promise<void> {
    if (!(await this.popover.isVisible())) await this.toggle.click();
    await expect(this.popover).toBeVisible();
  }

  async close(): Promise<void> {
    if (await this.popover.isVisible())
      await this.page.keyboard.press("Escape");
    await expect(this.popover).toBeHidden();
  }

  toolRow(name: string): Locator {
    return this.popover.getByRole("button", { name }).first();
  }

  async setToolEnabled(name: string, enabled: boolean): Promise<void> {
    await this.open();
    const row = this.toolRow(name);
    await row.hover();
    const desiredAction = enabled ? "Disable" : "Enable";
    const currentAction = row.getByRole("button", {
      name: enabled ? "Enable" : "Disable",
      exact: true,
    });
    if (await currentAction.isVisible()) await currentAction.click();
    await expect(
      row.getByRole("button", { name: desiredAction, exact: true })
    ).toBeVisible();
  }

  async openSearchSources(): Promise<void> {
    await this.open();
    const sourcesButton = this.popover.getByRole("button", {
      name: "Select Search Sources",
      exact: true,
    });
    await sourcesButton.click();
    await expect(
      this.popover.getByRole("button", { name: "Back", exact: true })
    ).toBeVisible();
  }
}
