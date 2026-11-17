import { type Locator, type Page, expect } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

/** The admin plugin list at /admin/plugins: the plugins that hold
 * integrations, with a link to each integration. */
export class AdminPluginsPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(): Promise<void> {
    await this.page.goto(ADMIN_ROUTES.PLUGINS.path);
    await expect(this.page).toHaveURL(/\/admin\/plugins(?:\?.*)?$/);
    await expect(
      this.page
        .getByLabel("admin-page-title")
        .getByText("Plugins", { exact: true })
    ).toBeVisible();
    await expect(this.page.getByRole("table")).toBeVisible();
  }

  /** Matches the plugin name cell only, as the row also names the
   * integrations. */
  pluginRow(name: string | RegExp): Locator {
    return this.page.getByRole("row").filter({
      has: this.page
        .locator("td:first-child")
        .getByText(name, { exact: typeof name === "string" }),
    });
  }

  async expectPluginVisible(name: string): Promise<void> {
    await expect(this.pluginRow(name).first()).toBeVisible();
  }

  async expectPluginAbsent(name: string | RegExp): Promise<void> {
    await expect(this.pluginRow(name)).toHaveCount(0);
  }

  integrationLink(integration: string): Locator {
    return this.page.getByRole("button", {
      name: `Open ${integration}`,
      exact: true,
    });
  }

  async openIntegration(integration: string): Promise<void> {
    await this.integrationLink(integration).first().click();
    await expect(this.page).toHaveURL(/\/admin\/integrations\/\d+(?:\?.*)?$/);
  }
}
