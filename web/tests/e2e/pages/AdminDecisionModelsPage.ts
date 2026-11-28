import { expect, type Page } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export class AdminDecisionModelsPage {
  constructor(readonly page: Page) {}

  /** Decision models live on the AI Models page. */
  async open(): Promise<void> {
    await this.page.goto(ADMIN_ROUTES.LLM_MODELS.path);
    await expect(
      this.page.getByLabel("admin-page-title").getByText("AI Models")
    ).toBeVisible();
  }

  async expectUnsetModel(): Promise<void> {
    await expect(this.page.getByPlaceholder("Not configured")).toHaveValue("");
    await expect(
      this.page.getByRole("button", { name: "Clear", exact: true })
    ).toHaveCount(0);
    await expect(
      this.page.getByText("Decisions", { exact: true })
    ).toBeVisible();
  }

  async openZoomSetup(): Promise<void> {
    // The Decisions card to connect Zoom, or its provider card once connected.
    await this.page
      .getByLabel(/^(Add Zoom Zoom AI Decisions|Zoom AI Decisions)$/)
      .first()
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
