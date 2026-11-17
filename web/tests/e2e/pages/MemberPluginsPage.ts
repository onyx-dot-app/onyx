import { type Locator, type Page, expect } from "@playwright/test";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";

export type MemberPluginFilter = "All" | "Skills" | "Integrations";

/** The member Plugins page at /app/plugins. */
export class MemberPluginsPage {
  readonly page: Page;
  readonly searchInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.searchInput = page.getByLabel("Search plugins", { exact: true });
  }

  async goto(): Promise<void> {
    await this.page.goto("/app/plugins");
    await expect(
      this.page.getByText("Plugins", { exact: true }).first()
    ).toBeVisible();
  }

  pluginCard(name: string): Locator {
    return this.page.getByRole("button", { name: `Open ${name}`, exact: true });
  }

  async filter(kind: MemberPluginFilter): Promise<void> {
    const button = this.page
      .getByRole("group", { name: "Plugin type", exact: true })
      .getByRole("button", { name: kind, exact: true });
    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
  }

  async search(query: string): Promise<void> {
    await this.searchInput.fill(query);
  }

  async expectPluginVisible(name: string): Promise<void> {
    await expect(this.pluginCard(name)).toBeVisible();
  }

  async expectPluginAbsent(name: string): Promise<void> {
    await expect(this.pluginCard(name)).toHaveCount(0);
  }

  /** Adds a personal MCP server with "Add Integration" ("For me" only) and
   * returns the new integration and its plugin. The page then shows the
   * plugin. */
  async addMcpServer(details: {
    name: string;
    url: string;
    /** A manual OAuth client, for a server that signs in with OAuth. */
    oauthClient?: { clientId: string; clientSecret: string };
  }): Promise<{ integrationId: number; pluginId: string }> {
    await this.page
      .getByRole("button", { name: "Add Integration", exact: true })
      .click();
    const dialog = this.page.getByRole("dialog");
    await dialog
      .getByRole("button", { name: "MCP server", exact: true })
      .click();
    await dialog
      .getByRole("textbox", { name: "Name", exact: true })
      .fill(details.name);
    await dialog
      .getByRole("textbox", { name: "Server URL", exact: true })
      .fill(details.url);
    await expect(
      dialog.getByRole("combobox", { name: "Owner", exact: true })
    ).toHaveCount(0);
    if (details.oauthClient) {
      const addForm = new AdminIntegrationsPage(this.page);
      await addForm.expectOAuthProbe();
      await addForm.fillOAuthClient(
        details.oauthClient.clientId,
        details.oauthClient.clientSecret
      );
    }
    const response = this.page.waitForResponse(
      (candidate) =>
        new URL(candidate.url()).pathname === "/api/admin/integrations" &&
        candidate.request().method() === "POST"
    );
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    const created = await response;
    expect(created.ok(), await created.text()).toBeTruthy();
    const body: { id: number; plugins: { plugin_id: string }[] } =
      await created.json();
    const pluginId = body.plugins[0]?.plugin_id;
    if (!pluginId) throw new Error("The new integration has no plugin");
    await expect(this.page).toHaveURL(new RegExp(`/app/plugins/${pluginId}`));
    return { integrationId: body.id, pluginId };
  }

  async openPlugin(name: string): Promise<void> {
    await this.pluginCard(name).click();
    await expect(this.page).toHaveURL(/\/app\/plugins\/[0-9a-f-]{36}/);
  }
}
