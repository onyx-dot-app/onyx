import { type Locator, type Page, expect } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export class AdminPluginsPage {
  readonly page: Page;
  readonly addButton: Locator;

  constructor(page: Page) {
    this.page = page;
    // The empty state repeats the header Add menu.
    this.addButton = page
      .getByRole("button", { name: "Add", exact: true })
      .first();
  }

  async goto(): Promise<void> {
    await this.page.goto(ADMIN_ROUTES.PLUGINS.path);
    await expect(this.page).toHaveURL(/\/admin\/plugins(?:\?.*)?$/);
    await expect(
      this.page
        .getByLabel("admin-page-title")
        .getByText("Plugins", { exact: true })
    ).toBeVisible();
    await expect(
      this.page.getByRole("status", { name: "Loading plugins", exact: true })
    ).toBeHidden();
  }

  async openAddMenu(): Promise<void> {
    await this.addButton.click();
  }

  async openAddMcp(): Promise<void> {
    await this.openAddMenu();
    await this.page.getByRole("menuitem", { name: "MCP", exact: true }).click();
    await this.page
      .getByRole("dialog", { name: "MCP", exact: true })
      .getByRole("button", { name: "Add custom MCP server", exact: true })
      .click();
  }

  async openAddOpenApi(): Promise<void> {
    await this.openAddMenu();
    await this.page
      .getByRole("menuitem", { name: "OpenAPI", exact: true })
      .click();
  }

  pluginLink(name: string): Locator {
    return this.page.getByRole("link", {
      name: new RegExp(
        `^(Manage|View) ${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`
      ),
    });
  }

  async expectPluginVisible(name: string): Promise<void> {
    await expect(this.pluginLink(name)).toBeVisible();
  }

  async expectPluginAbsent(name: string | RegExp): Promise<void> {
    await expect(
      this.page.getByRole("link").filter({ hasText: name })
    ).toHaveCount(0);
  }

  async openPlugin(name: string): Promise<void> {
    await this.pluginLink(name).click();
  }
}
