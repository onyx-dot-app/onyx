import { type Locator, type Page, expect } from "@playwright/test";

export class MemberPluginConnectionDialog {
  readonly page: Page;
  readonly dialog: Locator;
  readonly connectButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.dialog = page.getByRole("dialog");
    this.connectButton = this.dialog.getByRole("button", {
      name: "Connect",
      exact: true,
    });
  }

  async expectOpen(pluginName: string): Promise<void> {
    await expect(this.dialog).toBeVisible();
    await expect(
      this.dialog.getByText(`Connect ${pluginName}`, { exact: true })
    ).toBeVisible();
  }

  field(name: string): Locator {
    return this.dialog.getByLabel(name, { exact: true });
  }

  async expectFieldsVisible(names: string[]): Promise<void> {
    for (const name of names) await expect(this.field(name)).toBeVisible();
  }

  async fillField(name: string, value: string): Promise<void> {
    await this.field(name).fill(value);
  }

  async connectCredentials(): Promise<void> {
    const responsePromise = this.page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/mcp/user-credentials" &&
        response.request().method() === "POST"
    );
    await this.connectButton.click();
    const response = await responsePromise;
    expect(response.status(), await response.text()).toBe(200);
    await expect(this.dialog).toBeHidden();
  }

  async continueWithOAuth(pluginName: string): Promise<Page> {
    const popupPromise = this.page.waitForEvent("popup");
    await this.dialog
      .getByRole("button", { name: `Continue to ${pluginName}`, exact: true })
      .click();
    return popupPromise;
  }

  async expectClosed(): Promise<void> {
    await expect(this.dialog).toBeHidden({ timeout: 60_000 });
  }
}
