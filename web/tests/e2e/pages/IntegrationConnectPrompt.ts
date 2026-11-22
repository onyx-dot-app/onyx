import { type Locator, type Page, expect } from "@playwright/test";
import { IntegrationConnectDialog } from "@tests/e2e/pages/IntegrationConnectDialog";

/** The chat input's connect prompt for integrations that need sign-in. */
export class IntegrationConnectPrompt {
  readonly page: Page;
  readonly trigger: Locator;
  readonly dialog: IntegrationConnectDialog;

  constructor(page: Page) {
    this.page = page;
    this.trigger = page.getByRole("button", {
      name: /^\d+ integrations? needs? sign-in$/,
    });
    this.dialog = new IntegrationConnectDialog(page);
  }

  async expectCount(count: number): Promise<void> {
    await expect(this.trigger).toHaveAccessibleName(
      count === 1
        ? "1 integration needs sign-in"
        : `${count} integrations need sign-in`
    );
  }

  async expectHidden(): Promise<void> {
    await expect(this.trigger).toBeHidden();
  }

  async open(): Promise<void> {
    await this.trigger.click();
    await this.dialog.expectOpen();
  }
}
