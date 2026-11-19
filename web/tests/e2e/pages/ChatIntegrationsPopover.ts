import { type Locator, type Page, expect } from "@playwright/test";
import { ToolsPopover } from "@tests/e2e/pages/ToolsPopover";

/** The Integrations menu of the chat tools popover: the agent's
 * integrations. */
export class ChatIntegrationsPopover {
  readonly page: Page;
  readonly toggle: Locator;
  readonly popover: Locator;
  readonly actions: ToolsPopover;

  constructor(page: Page) {
    this.page = page;
    this.actions = new ToolsPopover(page);
    this.toggle = page.getByRole("button", {
      name: "Integrations",
      exact: true,
    });
    this.popover = page.getByRole("dialog").filter({
      has: page.getByRole("searchbox", {
        name: "Search integrations",
        exact: true,
      }),
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

  integrationSwitch(name: string): Locator {
    return this.popover.getByRole("switch", {
      name: `Use ${name} with this agent`,
      exact: true,
    });
  }

  private integrationRow(name: string): Locator {
    return this.popover.getByRole("presentation").filter({
      has: this.page.getByText(name, { exact: true }),
    });
  }

  async expectIntegrationVisible(name: string): Promise<void> {
    await this.open();
    await expect(this.integrationRow(name)).toBeVisible();
  }

  async expectIntegrationEnabled(
    name: string,
    enabled: boolean
  ): Promise<void> {
    await this.expectIntegrationVisible(name);
    await expect(this.integrationSwitch(name)).toHaveAttribute(
      "aria-checked",
      String(enabled)
    );
  }

  async setIntegrationEnabled(name: string, enabled: boolean): Promise<void> {
    await this.expectIntegrationVisible(name);
    const toggle = this.integrationSwitch(name);
    await expect(toggle).toBeEnabled();
    if ((await toggle.getAttribute("aria-checked")) !== String(enabled)) {
      await toggle.click();
    }
    await this.expectIntegrationEnabled(name, enabled);
  }

  async expectConnected(name: string): Promise<void> {
    await this.expectIntegrationVisible(name);
    await expect(this.integrationSwitch(name)).toBeVisible();
    await expect(this.integrationSwitch(name)).toBeEnabled();
    await expect(
      this.integrationRow(name).getByRole("button", {
        name: "Connect",
        exact: true,
      })
    ).toBeHidden();
  }
}
