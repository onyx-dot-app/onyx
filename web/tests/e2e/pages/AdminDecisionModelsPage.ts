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
}
