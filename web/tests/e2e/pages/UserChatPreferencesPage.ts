import { expect, type Locator, type Page } from "@playwright/test";

export class UserChatPreferencesPage {
  readonly sendBehavior: Locator;

  constructor(readonly page: Page) {
    this.sendBehavior = page.getByRole("combobox", {
      name: "Send Behavior While Working",
    });
  }

  async goto(): Promise<void> {
    await this.page.goto("/app/settings/chat-preferences");
    await expect(this.sendBehavior).toBeVisible();
  }

  async setSendBehavior(
    behavior: "After the current step" | "Interrupt current work"
  ): Promise<void> {
    await this.sendBehavior.click();
    const saved = this.page.waitForResponse((response) =>
      response.url().includes("/interrupt-on-send?")
    );
    await this.page
      .getByRole("option", { name: behavior, exact: true })
      .click();
    expect((await saved).ok()).toBe(true);
    await expect(this.sendBehavior).toHaveValue(behavior);
  }
}
