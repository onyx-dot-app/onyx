import { expect, type Locator, type Page } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export class AdminVoicePage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(): Promise<void> {
    await this.page.goto(ADMIN_ROUTES.VOICE.path);
    await this.page.waitForURL(`**${ADMIN_ROUTES.VOICE.path}**`);
    await expect(
      this.page.getByText("Speech to Text", { exact: true }).first()
    ).toBeVisible();
  }

  get zoomSttCard(): Locator {
    return this.page.getByLabel("voice-stt-scribe-live", { exact: true });
  }

  get zoomTtsCard(): Locator {
    return this.page.getByLabel("voice-tts-scribe-live", { exact: true });
  }

  get modal(): Locator {
    return this.page.getByRole("dialog");
  }

  get apiKeyInput(): Locator {
    return this.modal.getByLabel("API Key");
  }

  get apiSecretInput(): Locator {
    return this.modal.getByLabel("API Secret");
  }

  get languageSelect(): Locator {
    return this.modal.getByLabel("Spoken Language");
  }

  get connectButton(): Locator {
    return this.modal.getByRole("button", { name: "Connect" });
  }

  get updateButton(): Locator {
    return this.modal.getByRole("button", { name: "Update" });
  }

  async expectZoomCardUnderSpeechToTextOnly(): Promise<void> {
    await expect(this.zoomSttCard).toBeVisible();
    await expect(this.zoomSttCard).toContainText("Zoom Scribe");
    await expect(this.zoomTtsCard).toHaveCount(0);
  }

  async openZoomSetupModal(): Promise<void> {
    await this.zoomSttCard.getByRole("button", { name: "Connect" }).click();
    await expect(this.modal).toBeVisible();
    await expect(this.modal).toContainText("Set up Zoom Scribe");
  }

  async openZoomEditModal(): Promise<void> {
    await this.zoomSttCard.hover();
    await this.zoomSttCard
      .getByRole("button", { name: "Edit Zoom Scribe" })
      .click();
    await expect(this.modal).toBeVisible();
    await expect(this.modal).toContainText("Configure Zoom Scribe");
  }

  async expectZoomSetupFields(): Promise<void> {
    await expect(this.apiKeyInput).toBeVisible();
    await expect(this.apiSecretInput).toBeVisible();
    await expect(this.languageSelect).toBeVisible();
  }

  async expectLanguageValue(language: string): Promise<void> {
    await expect(this.languageSelect).toContainText(language);
  }

  async fillZoomCredentials(credentials: {
    apiKey: string;
    apiSecret: string;
  }): Promise<void> {
    await this.apiKeyInput.fill(credentials.apiKey);
    await this.apiSecretInput.fill(credentials.apiSecret);
  }

  async selectLanguage(language: string): Promise<void> {
    await this.languageSelect.click();
    await this.page.getByRole("option", { name: language }).click();
    await this.expectLanguageValue(language);
  }

  async connectZoom(): Promise<void> {
    await expect(this.connectButton).toBeEnabled();
    await this.connectButton.click();
  }

  async updateZoom(): Promise<void> {
    await expect(this.updateButton).toBeEnabled();
    await this.updateButton.click();
  }
}
