import { type Locator, type Page, expect } from "@playwright/test";
import { IntegrationCredentialsDialog } from "@tests/e2e/pages/IntegrationCredentialsDialog";

export class RequiredIntegrationGate {
  readonly page: Page;
  readonly gate: Locator;
  readonly continueButton: Locator;
  readonly adminDescription: Locator;

  constructor(page: Page) {
    this.page = page;
    this.gate = page.getByRole("dialog", { name: "Connect your work tools" });
    this.continueButton = this.gate.getByRole("button", {
      name: "Continue",
      exact: true,
    });
    this.adminDescription = this.gate.getByText(
      "Members must connect these integrations before they can use Onyx. You can continue without them because you are an admin."
    );
  }

  async gotoApp(): Promise<void> {
    await this.page.goto("/app");
  }

  async gotoNewTabPage(): Promise<void> {
    await this.page.goto("/nrf");
  }

  async expectVisible(): Promise<void> {
    await expect(this.gate).toBeVisible();
  }

  async expectHidden(): Promise<void> {
    await expect(this.gate).toBeHidden();
  }

  row(name: string): Locator {
    return this.gate.getByRole("group", { name, exact: true });
  }

  async expectRequired(name: string): Promise<void> {
    await expect(
      this.row(name).getByRole("button", { name: `Connect ${name}` })
    ).toBeVisible();
  }

  async expectProgress(connected: number, total: number): Promise<void> {
    await expect(
      this.gate.getByText(`${connected} of ${total} connected`)
    ).toBeVisible();
  }

  async expectConnected(name: string): Promise<void> {
    await expect(
      this.row(name).getByText("Connected", { exact: true })
    ).toBeVisible();
  }

  async expectAdminDescription(): Promise<void> {
    await expect(this.adminDescription).toBeVisible();
  }

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

  async pressEscape(): Promise<void> {
    await this.page.keyboard.press("Escape");
  }

  async connectWithCredentials(
    name: string,
    fields: Record<string, string>
  ): Promise<void> {
    await this.row(name).getByRole("button").click();
    await new IntegrationCredentialsDialog(this.page).submit(fields);
  }

  async continue(): Promise<void> {
    await this.continueButton.click();
  }
}
