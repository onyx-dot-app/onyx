import { type Locator, type Page, expect } from "@playwright/test";

export type MemberPluginTab =
  | "Overview"
  | "Skills"
  | "Integrations"
  | "Versions";
export type IntegrationStatusLabel =
  | "Connected"
  | "Not connected"
  | "Needs reconnect"
  | "Not set up";

/** One plugin at /app/plugins/[pluginId]. */
export class MemberPluginDetailPage {
  readonly page: Page;
  readonly credentialsDialog: Locator;

  constructor(page: Page) {
    this.page = page;
    this.credentialsDialog = page.getByRole("dialog").filter({
      has: page.getByText("Enter your credentials. Only you use them.", {
        exact: true,
      }),
    });
  }

  async goto(pluginId: string, tab?: MemberPluginTab): Promise<void> {
    const query = tab && tab !== "Overview" ? `?tab=${tab.toLowerCase()}` : "";
    await this.page.goto(`/app/plugins/${pluginId}${query}`);
  }

  async openTab(tab: MemberPluginTab): Promise<void> {
    const trigger = this.page.getByRole("tab", { name: tab, exact: true });
    await trigger.click();
    await expect(trigger).toHaveAttribute("aria-selected", "true");
  }

  async expectTabs(tabs: MemberPluginTab[]): Promise<void> {
    await expect(this.page.getByRole("tab")).toHaveText(tabs);
  }

  pluginSwitch(plugin: string): Locator {
    return this.page.getByRole("switch", {
      name: `Use ${plugin}`,
      exact: true,
    });
  }

  /** The user's on/off switch on the Overview tab. */
  async setPluginEnabled(plugin: string, enabled: boolean): Promise<void> {
    const toggle = this.pluginSwitch(plugin);
    await expect(toggle).toBeEnabled();
    if ((await toggle.getAttribute("aria-checked")) !== String(enabled))
      await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", String(enabled));
  }

  connectButton(integration: string): Locator {
    return this.page.getByRole("button", {
      name: `Connect ${integration}`,
      exact: true,
    });
  }

  reconnectButton(integration: string): Locator {
    return this.page.getByRole("button", {
      name: `Reconnect ${integration}`,
      exact: true,
    });
  }

  disconnectButton(integration: string): Locator {
    return this.page.getByRole("button", {
      name: `Disconnect ${integration}`,
      exact: true,
    });
  }

  /** Clicks Connect on the row of an integration. */
  async startConnect(integration: string): Promise<void> {
    await this.connectButton(integration).click();
  }

  /** Waits for the status text of an integration row. */
  async expectStatus(status: IntegrationStatusLabel | string): Promise<void> {
    await expect(this.page.getByText(status, { exact: true })).toBeVisible();
  }

  /** Opens the API key form, fills each field by label and connects. */
  async connectWithCredentials(
    integration: string,
    fields: Record<string, string>
  ): Promise<void> {
    await this.startConnect(integration);
    await expect(this.credentialsDialog).toBeVisible();
    for (const [label, value] of Object.entries(fields))
      await this.credentialsDialog
        .getByLabel(label, { exact: true })
        .fill(value);
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/integrations\/\d+\/connection$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "PUT"
    );
    await this.credentialsDialog
      .getByRole("button", { name: "Connect", exact: true })
      .click();
    expect((await response).ok()).toBeTruthy();
    await expect(this.credentialsDialog).toBeHidden();
    await expect(this.disconnectButton(integration)).toBeVisible();
  }

  async disconnect(integration: string): Promise<void> {
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/integrations\/\d+\/connection$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "DELETE"
    );
    await this.disconnectButton(integration).click();
    expect((await response).ok()).toBeTruthy();
    await expect(this.connectButton(integration)).toBeVisible();
  }

  alwaysAllowSwitch(action: string): Locator {
    return this.page.getByRole("switch", {
      name: `Always allow ${action}`,
      exact: true,
    });
  }

  /** Saves the user's Always allow choice of one action on the Integrations tab. */
  async setAlwaysAllow(action: string, allow: boolean): Promise<void> {
    const toggle = this.alwaysAllowSwitch(action);
    await expect(toggle).toBeEnabled();
    if ((await toggle.getAttribute("aria-checked")) === String(allow)) return;
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/action-policies\/integration\/\d+$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "PUT"
    );
    await toggle.click();
    expect((await response).ok()).toBeTruthy();
    await expect(toggle).toHaveAttribute("aria-checked", String(allow));
  }
}
