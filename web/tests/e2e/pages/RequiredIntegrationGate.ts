import { type Locator, type Page, expect } from "@playwright/test";
import { IntegrationCredentialsDialog } from "@tests/e2e/pages/IntegrationCredentialsDialog";

/** The full-screen page that asks for each Required integration. */
export class RequiredIntegrationGate {
  readonly page: Page;
  readonly gate: Locator;
  readonly continueButton: Locator;
  readonly adminNote: Locator;

  constructor(page: Page) {
    this.page = page;
    this.gate = page.getByRole("dialog", { name: "Connect your work tools" });
    this.continueButton = this.gate.getByRole("button", {
      name: "Continue",
      exact: true,
    });
    this.adminNote = this.gate.getByText(
      "You can continue without connecting because you are an admin."
    );
  }

  async gotoApp(): Promise<void> {
    await this.page.goto("/app");
  }

  async expectVisible(): Promise<void> {
    await expect(this.gate).toBeVisible();
  }

  async expectHidden(): Promise<void> {
    await expect(this.gate).toBeHidden();
  }

  row(name: string): Locator {
    return this.gate.getByText(name, { exact: true });
  }

  async expectRequired(name: string): Promise<void> {
    await expect(this.row(name)).toBeVisible();
    await expect(this.gate.getByText("Required by your admin")).toBeVisible();
  }

  async expectConnected(name: string): Promise<void> {
    await expect(this.row(name)).toBeVisible();
    await expect(
      this.gate.getByText("Connected", { exact: true })
    ).toBeVisible();
  }

  async expectAdminNote(): Promise<void> {
    await expect(this.adminNote).toBeVisible();
  }

  /** The gate is gone and the chat input takes typing. */
  async expectAppUsable(): Promise<void> {
    await this.expectHidden();
    const input = this.page.locator("#onyx-chat-input-textbox");
    await input.click();
    await input.fill("hello");
    await expect(input).toContainText("hello");
  }

  async expectContinueDisabled(): Promise<void> {
    await expect(this.continueButton).toBeDisabled();
  }

  async expectContinueEnabled(): Promise<void> {
    await expect(this.continueButton).toBeEnabled();
  }

  /** Escape must not close the gate. */
  async pressEscape(): Promise<void> {
    await this.page.keyboard.press("Escape");
  }

  async connectWithCredentials(
    name: string,
    fields: Record<string, string>
  ): Promise<void> {
    await this.gate
      .getByRole("button", { name: `Connect ${name}`, exact: true })
      .click();
    await new IntegrationCredentialsDialog(this.page).submit(fields);
  }

  async continue(): Promise<void> {
    await this.continueButton.click();
  }
}
