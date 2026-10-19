import { type Locator, type Page, expect } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export class AdminPluginsPage {
  readonly page: Page;
  readonly addButton: Locator;

  constructor(page: Page) {
    this.page = page;
    // The empty state repeats the header Add menu.
    this.addButton = page
      .getByRole("button", { name: "New Plugin", exact: true })
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
    await this.addMenuItem("MCP").click();
    await this.page
      .getByRole("dialog", { name: "MCP", exact: true })
      .getByRole("button", { name: "Add custom MCP server", exact: true })
      .click();
  }

  async openAddOpenApi(): Promise<void> {
    await this.openAddMenu();
    await this.addMenuItem("OpenAPI").click();
  }

  /** A New Plugin menu entry; its description is part of its name. */
  addMenuItem(title: string): Locator {
    return this.page.getByRole("menuitem", {
      name: new RegExp(`^${escapeRegExp(title)}( |$)`),
    });
  }

  /** Plugin cards: labelled `<div>`s, so a card's own buttons never match. */
  private cards(): Locator {
    return this.page
      .getByLabel(/^(Manage|View) /)
      .and(this.page.locator("div"));
  }

  pluginCard(name: string): Locator {
    return this.page
      .getByLabel(new RegExp(`^(Manage|View) ${escapeRegExp(name)}$`))
      .and(this.page.locator("div"));
  }

  async expectPluginVisible(name: string): Promise<void> {
    await expect(this.pluginCard(name)).toBeVisible();
  }

  async expectPluginAbsent(name: string | RegExp): Promise<void> {
    await expect(this.cards().filter({ hasText: name })).toHaveCount(0);
  }

  async openPlugin(name: string): Promise<void> {
    await this.pluginCard(name).click();
  }
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
