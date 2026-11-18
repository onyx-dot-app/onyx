import { type Locator, type Page, expect } from "@playwright/test";
import { IntegrationCredentialsDialog } from "@tests/e2e/pages/IntegrationCredentialsDialog";

/** The "Connect Integrations" dialog of chat: one row per integration with
 * Connect or Reconnect. The API key form opens over it. */
export class IntegrationConnectDialog {
  readonly page: Page;
  readonly dialog: Locator;
  readonly credentials: IntegrationCredentialsDialog;

  constructor(page: Page) {
    this.page = page;
    this.dialog = page.getByRole("dialog").filter({
      has: page.getByText("Connect Integrations", { exact: true }),
    });
    this.credentials = new IntegrationCredentialsDialog(page);
  }

  async expectOpen(): Promise<void> {
    await expect(this.dialog).toBeVisible();
  }

  connectButton(name: string): Locator {
    return this.dialog.getByRole("button", {
      name: `Connect ${name}`,
      exact: true,
    });
  }

  reconnectButton(name: string): Locator {
    return this.dialog.getByRole("button", {
      name: `Reconnect ${name}`,
      exact: true,
    });
  }

  /** Clicks Connect on the row of an integration. */
  async startConnect(name: string): Promise<void> {
    await this.connectButton(name).click();
  }

  /** Fills the API key form by field label and connects. */
  async submitCredentials(fields: Record<string, string>): Promise<void> {
    await this.credentials.submit(fields);
  }

  /** The row of one integration (an Opal ContentAction). */
  row(name: string): Locator {
    return this.dialog.locator(".opal-content-action").filter({
      has: this.page.getByText(name, { exact: true }),
    });
  }

  async expectConnected(name: string): Promise<void> {
    await expect(
      this.row(name).getByText("Connected", { exact: true })
    ).toBeVisible();
    await expect(this.connectButton(name)).toBeHidden();
    await expect(this.reconnectButton(name)).toBeHidden();
  }

  async close(): Promise<void> {
    await this.dialog
      .getByRole("button", { name: "Done", exact: true })
      .click();
    await expect(this.dialog).toBeHidden();
  }
}
