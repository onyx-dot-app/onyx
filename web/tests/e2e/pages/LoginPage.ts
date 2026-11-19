import { type Locator, type Page, expect } from "@playwright/test";

/** The email and password login page at `/auth/login`. */
export class LoginPage {
  readonly page: Page;
  readonly emailInput: Locator;
  readonly passwordInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.emailInput = page.getByTestId("email");
    this.passwordInput = page.getByTestId("password");
  }

  /** Opens the app root, which sends a signed-out visitor to this page. */
  async gotoAppRoot(): Promise<void> {
    await this.page.goto("/");
  }

  async reload(): Promise<void> {
    await this.page.reload();
  }

  async expectVisible(): Promise<void> {
    await expect(this.page).toHaveURL(/\/auth\/login/);
    await expect(this.emailInput).toBeVisible();
    await expect(this.passwordInput).toBeVisible();
  }
}
