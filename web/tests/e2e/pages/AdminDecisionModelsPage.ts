import { expect, type Page } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export class AdminDecisionModelsPage {
  constructor(readonly page: Page) {}

  async openFromChatPreferences(): Promise<void> {
    await this.page.goto(ADMIN_ROUTES.CHAT_PREFERENCES.path);
    await expect(this.page.getByLabel("admin-page-title")).toBeVisible();
    await expect(
      this.page.getByRole("group", { name: "Decision model", exact: true })
    ).toHaveCount(0);
    await this.page
      .getByRole("link", { name: "Decision Models", exact: true })
      .click();
    await this.page.waitForURL(`**${ADMIN_ROUTES.DECISION_MODELS.path}`);
    await expect(
      this.page
        .getByLabel("admin-page-title")
        .getByText("Decision Models", { exact: true })
    ).toBeVisible();
  }

  async expectUnsetModel(): Promise<void> {
    await expect(this.page.getByPlaceholder("Not configured")).toHaveValue("");
    await expect(
      this.page.getByRole("button", { name: "Clear", exact: true })
    ).toHaveCount(0);
    await expect(
      this.page.getByText("Providers", { exact: true })
    ).toBeVisible();
  }

  async openZoomSetup(): Promise<void> {
    await this.page
      .getByTestId(/^decision-provider-zoom_ai-/)
      .getByRole("button", { name: /^(Connect|Edit )/ })
      .click();
    const dialog = this.page.getByRole("dialog");
    await expect(
      dialog.getByText("Connect Zoom AI Services", { exact: true })
    ).toBeVisible();
    await expect(dialog.getByLabel("API Key")).toBeVisible();
    await expect(dialog.getByLabel("API Secret")).toBeVisible();
    await expect(dialog).toContainText(
      "Use one connection for Zoom Scribe and Zoom AI Decisions. Changes apply to both."
    );
    await expect(
      dialog.getByRole("link", { name: "Set up Voice" })
    ).toHaveCount(0);
  }
}
