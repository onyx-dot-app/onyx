import { type Locator, type Page, expect } from "@playwright/test";

/** The "Connect Integrations" dialog of chat: one row per integration with
 * Connect or Reconnect. The API key form opens over it. */
export class IntegrationConnectDialog {
  readonly page: Page;
  readonly dialog: Locator;
  readonly credentialsDialog: Locator;

  constructor(page: Page) {
    this.page = page;
    this.dialog = page.getByRole("dialog").filter({
      has: page.getByText("Connect Integrations", { exact: true }),
    });
    this.credentialsDialog = page.getByRole("dialog").filter({
      has: page.getByText("Enter your credentials. Only you use them.", {
        exact: true,
      }),
    });
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

  /** Fills the API key form by field label and connects. */
  async submitCredentials(fields: Record<string, string>): Promise<void> {
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
  }

  async expectConnected(name: string): Promise<void> {
    await expect(this.dialog.getByText(name, { exact: true })).toBeVisible();
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
