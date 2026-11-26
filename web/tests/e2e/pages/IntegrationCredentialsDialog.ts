import { type Locator, type Page, expect } from "@playwright/test";

/** The API key form of one integration that the member fills to connect. */
export class IntegrationCredentialsDialog {
  readonly page: Page;
  readonly dialog: Locator;

  constructor(page: Page) {
    this.page = page;
    this.dialog = page.getByRole("dialog").filter({
      has: page.getByText("Enter your credentials. Only you use them.", {
        exact: true,
      }),
    });
  }

  /** Fills each field by label, connects, and waits for the dialog to close. */
  async submit(fields: Record<string, string>): Promise<void> {
    await expect(this.dialog).toBeVisible();
    for (const [label, value] of Object.entries(fields))
      await this.dialog.getByLabel(label, { exact: true }).fill(value);
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/integrations\/\d+\/connection$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "PUT"
    );
    await this.dialog
      .getByRole("button", { name: "Connect", exact: true })
      .click();
    expect((await response).ok()).toBeTruthy();
    await expect(this.dialog).toBeHidden();
  }
}
