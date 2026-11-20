import { type Locator, type Page, expect } from "@playwright/test";
import { IntegrationCredentialsDialog } from "@tests/e2e/pages/IntegrationCredentialsDialog";

export type IntegrationPageTab = "Overview" | "Configuration" | "Actions";
// An expired connection shows its reason in the row, not a label: pass the
// reason text to expectStatus.
export type IntegrationStatusLabel =
  | "Connected"
  | "Not connected"
  | "Not set up";

/** One integration of a member at /app/customize/integrations/[id]. */
export class CustomizeIntegrationPage {
  readonly page: Page;
  private readonly configuration: Locator;
  readonly credentials: IntegrationCredentialsDialog;

  constructor(page: Page) {
    this.page = page;
    this.configuration = page.getByRole("tabpanel", { name: "Configuration" });
    this.credentials = new IntegrationCredentialsDialog(page);
  }

  async goto(integrationId: number, tab?: IntegrationPageTab): Promise<void> {
    const query = tab && tab !== "Overview" ? `?tab=${tab.toLowerCase()}` : "";
    await this.page.goto(
      `/app/customize/integrations/${integrationId}${query}`
    );
    await expect(
      this.page.getByRole("tab", { name: tab ?? "Overview", exact: true })
    ).toHaveAttribute("aria-selected", "true");
  }

  async openTab(tab: IntegrationPageTab): Promise<void> {
    const trigger = this.page.getByRole("tab", { name: tab, exact: true });
    await trigger.click();
    await expect(trigger).toHaveAttribute("aria-selected", "true");
  }

  integrationSwitch(integration: string): Locator {
    return this.page.getByRole("switch", {
      name: `Use ${integration}`,
      exact: true,
    });
  }

  /** The user's on/off switch on the Overview tab. On means on everywhere. */
  async setEnabled(integration: string, enabled: boolean): Promise<void> {
    const toggle = this.integrationSwitch(integration);
    await expect(toggle).toBeEnabled();
    if ((await toggle.getAttribute("aria-checked")) !== String(enabled))
      await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", String(enabled));
  }

  connectButton(integration: string): Locator {
    return this.configuration.getByRole("button", {
      name: `Connect ${integration}`,
      exact: true,
    });
  }

  reconnectButton(integration: string): Locator {
    return this.configuration.getByRole("button", {
      name: `Reconnect ${integration}`,
      exact: true,
    });
  }

  disconnectButton(integration: string): Locator {
    return this.configuration.getByRole("button", {
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
    await expect(
      this.configuration.getByText(status, { exact: true })
    ).toBeVisible();
  }

  /** Opens the API key form, fills each field by label and connects. */
  async connectWithCredentials(
    integration: string,
    fields: Record<string, string>
  ): Promise<void> {
    await this.startConnect(integration);
    await this.credentials.submit(fields);
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

  /** Saves the user's Always allow choice of one action on the Actions tab. */
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

  /** Opens "Share" from the "..." menu and adds one person by email. */
  async shareWith(integration: string, email: string): Promise<void> {
    await this.page
      .getByRole("button", { name: `More actions for ${integration}` })
      .click();
    await this.page
      .getByRole("menuitem", { name: "Share", exact: true })
      .click();
    const dialog = this.page.getByRole("dialog", {
      name: `Share ${integration}`,
    });
    await expect(dialog).toBeVisible();
    await dialog
      .getByPlaceholder("Add users, groups, and accounts")
      .fill(email);
    await this.page.getByRole("option", { name: email }).click();
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/integrations\/\d+\/access$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "PUT"
    );
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    expect((await response).ok()).toBeTruthy();
    await expect(dialog).toBeHidden();
  }
}
