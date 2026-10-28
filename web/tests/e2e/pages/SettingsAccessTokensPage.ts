import { expect, type Page } from "@playwright/test";
import * as yup from "yup";

const createdTokenSchema = yup
  .object({
    id: yup.number().integer().required(),
    token: yup
      .string()
      .matches(/^onyx_pat_/)
      .required(),
    scopes: yup.array().of(yup.string().required()).nullable().defined(),
  })
  .required();

export class SettingsAccessTokensPage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/app/settings/accounts-access");
    await expect(
      this.page.getByRole("button", { name: "New Access Token", exact: true })
    ).toBeVisible();
  }

  async createFullAccessToken(name: string) {
    await this.page
      .getByRole("button", { name: "New Access Token", exact: true })
      .click();
    await this.page
      .getByPlaceholder("Name your token", { exact: true })
      .fill(name);
    await expect(
      this.page.getByText(
        "Includes your permissions at creation. New permissions require a new token.",
        { exact: true }
      )
    ).toBeVisible();
    await expect(
      this.page.getByRole("combobox", {
        name: "Select permissions",
        exact: true,
      })
    ).toHaveValue("Full access");

    const responsePromise = this.page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/user/pats" &&
        response.request().method() === "POST"
    );
    await this.page
      .getByRole("button", { name: "Create Token", exact: true })
      .click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const body: unknown = await response.json();
    const token = await createdTokenSchema.validate(body, { strict: true });
    await expect(
      this.page.getByRole("button", { name: "Copy Token" })
    ).toBeVisible();
    await expect(this.page.locator("code")).toHaveText(/^onyx_pat_\S+$/);
    await this.page.keyboard.press("Escape");
    await expect(this.page.getByText(name, { exact: true })).toBeVisible();
    return token;
  }

  async expectListedScopes(name: string, text: string): Promise<void> {
    const row = this.page
      .locator(".opal-attachment-item-button")
      .filter({ has: this.page.getByText(name, { exact: true }) });
    await expect(row).toContainText(text);
  }
}
