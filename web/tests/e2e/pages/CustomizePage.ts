import { type Locator, type Page, expect } from "@playwright/test";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";

export type CustomizeTab = "Plugins" | "Skills" | "Integrations";

/** The member Customize page: /app/customize/plugins, /skills and
 * /integrations. */
export class CustomizePage {
  readonly page: Page;
  readonly searchInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.searchInput = page.getByLabel("Search", { exact: true });
  }

  async goto(tab: CustomizeTab = "Plugins"): Promise<void> {
    await this.page.goto(`/app/customize/${tab.toLowerCase()}`);
    await expect(
      this.page.getByRole("tab", { name: tab, exact: true })
    ).toHaveAttribute("aria-selected", "true");
  }

  /** Opens a tab and waits for its list, so a next click does not race the
   * route that is still loading. */
  async openTab(tab: CustomizeTab): Promise<void> {
    await this.page.getByRole("tab", { name: tab, exact: true }).click();
    await expect(this.page).toHaveURL(
      new RegExp(`/app/customize/${tab.toLowerCase()}$`)
    );
    await expect(
      tab === "Integrations"
        ? this.page
            .getByRole("table")
            .or(this.page.getByText("No integrations yet", { exact: true }))
        : this.page
            .getByRole("region")
            .first()
            .or(
              this.page.getByText(
                tab === "Skills" ? "No skills yet" : "No plugins yet",
                { exact: true }
              )
            )
    ).toBeVisible();
  }

  /** Opens Customize from the app sidebar; it lands on the Skills tab. */
  async openFromSidebar(): Promise<void> {
    await this.page.goto("/app");
    await this.page
      .getByRole("link", { name: "Customize", exact: true })
      .click();
    await expect(this.page).toHaveURL(/\/app\/customize\/skills$/);
  }

  async expectSkillInGroup(name: string, group: string): Promise<void> {
    await expect(
      this.page
        .getByRole("region", { name: group })
        .getByText(name, { exact: true })
    ).toBeVisible();
  }

  async turnOffSkill(name: string): Promise<void> {
    await this.page
      .getByRole("button", { name: `More for ${name}`, exact: true })
      .click();
    await this.page
      .getByRole("menuitem", { name: "Turn off", exact: true })
      .click();
  }

  /** An off skill shows Disabled and a Turn on button in its row. */
  async expectSkillOff(name: string): Promise<void> {
    const row = this.skillRow(name);
    await expect(row.getByText("Disabled", { exact: true })).toBeVisible();
    await expect(
      row.getByRole("button", { name: "Turn on", exact: true })
    ).toBeVisible();
  }

  skillRow(name: string): Locator {
    return this.page.getByRole("button", { name: `Open ${name}`, exact: true });
  }

  integrationRow(name: string): Locator {
    return this.page.getByRole("row", { name: `Open ${name}`, exact: true });
  }

  async search(query: string): Promise<void> {
    await this.searchInput.fill(query);
  }

  async expectIntegrationVisible(name: string): Promise<void> {
    await expect(this.integrationRow(name)).toBeVisible();
  }

  async expectIntegrationAbsent(name: string): Promise<void> {
    await expect(this.integrationRow(name)).toHaveCount(0);
  }

  async openAddMenu(): Promise<void> {
    await this.page.getByRole("button", { name: "Add", exact: true }).click();
  }

  /** Adds a personal MCP server from the Add page of the Integrations tab
   * ("For me" only) and returns the new integration and its plugin. The page
   * then shows the integration on its Configuration tab. */
  async addMcpServer(details: {
    name: string;
    url: string;
    /** For a server that signs in with OAuth; without a client, Onyx registers one. */
    oauth?: { client: { clientId: string; clientSecret: string } | null };
  }): Promise<{ integrationId: number; pluginId: string }> {
    await this.openAddMenu();
    await this.page
      .getByRole("menuitem", { name: "Add integration", exact: true })
      .click();
    await expect(this.page).toHaveURL(/\/app\/customize\/integrations\/new$/);
    const addPage = new AdminIntegrationsPage(this.page);
    const form = addPage.addForm;
    await form.getByRole("radio", { name: "MCP Server", exact: true }).click();
    await form
      .getByRole("textbox", { name: "Name", exact: true })
      .fill(details.name);
    await form
      .getByRole("textbox", { name: "Server URL", exact: true })
      .fill(details.url);
    await expect(
      form.getByRole("combobox", { name: "Owner", exact: true })
    ).toHaveCount(0);
    if (details.oauth) {
      await addPage.expectOAuthProbe();
      if (details.oauth.client) {
        await addPage.fillOAuthClient(
          details.oauth.client.clientId,
          details.oauth.client.clientSecret
        );
      }
    }
    const response = this.page.waitForResponse(
      (candidate) =>
        new URL(candidate.url()).pathname === "/api/admin/integrations" &&
        candidate.request().method() === "POST"
    );
    await form.getByRole("button", { name: "Add", exact: true }).click();
    const created = await response;
    expect(created.ok(), await created.text()).toBeTruthy();
    const body: { id: number; plugins: { plugin_id: string }[] } =
      await created.json();
    const pluginId = body.plugins[0]?.plugin_id;
    if (!pluginId) throw new Error("The new integration has no plugin");
    await expect(this.page).toHaveURL(
      new RegExp(`/app/customize/integrations/${body.id}\\?tab=configuration`)
    );
    return { integrationId: body.id, pluginId };
  }

  async openIntegration(name: string): Promise<void> {
    await this.integrationRow(name).click();
    await expect(this.page).toHaveURL(/\/app\/customize\/integrations\/\d+/);
  }

  /** Opens a plugin from the Plugins tab. */
  async openPlugin(name: string): Promise<void> {
    await this.skillRow(name).click();
    await expect(this.page).toHaveURL(
      /\/app\/customize\/plugins\/[0-9a-f-]{36}/
    );
  }
}
