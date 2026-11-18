import { type Locator, type Page, expect } from "@playwright/test";
import { ToolsPopover } from "@tests/e2e/pages/ToolsPopover";

/** The Plugins menu of the chat tools popover: the agent's plugins. */
export class ChatPluginsPopover {
  readonly page: Page;
  readonly toggle: Locator;
  readonly popover: Locator;
  readonly actions: ToolsPopover;

  constructor(page: Page) {
    this.page = page;
    this.actions = new ToolsPopover(page);
    this.toggle = page.getByRole("button", { name: "Plugins", exact: true });
    this.popover = page.getByRole("dialog").filter({
      has: page.getByRole("searchbox", { name: "Search plugins", exact: true }),
    });
  }

  async open(): Promise<void> {
    if (!(await this.popover.isVisible())) {
      await this.actions.open();
      await this.toggle.click();
    }
    await expect(this.popover).toBeVisible();
  }

  async close(): Promise<void> {
    if (await this.popover.isVisible())
      await this.page.keyboard.press("Escape");
    await expect(this.popover).toBeHidden();
    await this.actions.close();
  }

  pluginSwitch(name: string): Locator {
    return this.popover.getByRole("switch", {
      name: `Use ${name} with this agent`,
      exact: true,
    });
  }

  private pluginRow(name: string): Locator {
    return this.popover.getByRole("presentation").filter({
      has: this.page.getByText(name, { exact: true }),
    });
  }

  async expectPluginVisible(name: string): Promise<void> {
    await this.open();
    await expect(this.pluginRow(name)).toBeVisible();
  }

  async expectPluginEnabled(name: string, enabled: boolean): Promise<void> {
    await this.expectPluginVisible(name);
    await expect(this.pluginSwitch(name)).toHaveAttribute(
      "aria-checked",
      String(enabled)
    );
  }

  async setPluginEnabled(name: string, enabled: boolean): Promise<void> {
    await this.expectPluginVisible(name);
    const toggle = this.pluginSwitch(name);
    await expect(toggle).toBeEnabled();
    if ((await toggle.getAttribute("aria-checked")) !== String(enabled)) {
      await toggle.click();
    }
    await this.expectPluginEnabled(name, enabled);
  }

  async expectConnected(name: string): Promise<void> {
    await this.expectPluginVisible(name);
    await expect(this.pluginSwitch(name)).toBeVisible();
    await expect(this.pluginSwitch(name)).toBeEnabled();
    await expect(
      this.pluginRow(name).getByRole("button", { name: "Connect", exact: true })
    ).toBeHidden();
  }
}
