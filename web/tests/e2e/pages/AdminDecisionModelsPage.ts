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
    await expect(this.page.getByLabel("admin-page-title")).toHaveText(
      "Decision Models"
    );
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
    const optionsResponse = this.page.waitForResponse((response) =>
      response.url().endsWith("/api/admin/llm/built-in/options/zoom_ai")
    );
    await this.page
      .getByTestId(/^decision-provider-zoom_ai-/)
      .getByRole("button")
      .click();
    expect((await optionsResponse).status()).toBe(200);
    const dialog = this.page.getByRole("dialog");
    await expect(
      dialog.getByText("Connect Zoom AI Decisions", { exact: true })
    ).toBeVisible();
    await expect(
      dialog
        .getByRole("combobox", { name: "Select a Zoom Scribe connection" })
        .or(dialog.getByRole("link", { name: "Set up Voice" }))
    ).toBeVisible();
  }
}
