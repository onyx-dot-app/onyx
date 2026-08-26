import { expect, type Locator, type Page } from "@playwright/test";

const COMPATIBLE_CARD_LABEL = "voice-stt-openai-compatible-stt";

export class AdminVoicePage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  private compatibleCard(): Locator {
    return this.page.getByLabel(COMPATIBLE_CARD_LABEL, { exact: true });
  }

  private setupDialog(): Locator {
    return this.page.getByRole("dialog", {
      name: /(?:set up|configure) OpenAI-Compatible/i,
    });
  }

  async goto(): Promise<void> {
    await this.page.goto("/admin/voice");
    await expect(this.compatibleCard()).toBeVisible({ timeout: 10000 });
  }

  async openSetup(): Promise<void> {
    await this.compatibleCard()
      .getByRole("button", { name: "Connect" })
      .click();
    await expect(this.setupDialog()).toBeVisible();
  }

  async expectSetupGuidance(): Promise<void> {
    await expect(this.setupDialog()).toContainText("/v1/audio/transcriptions");
    await expect(this.setupDialog()).toContainText("chunked audio");
    await expect(this.setupDialog()).toContainText("host.docker.internal");
  }

  async fillSetup(apiBase: string, model: string): Promise<void> {
    await this.setupDialog().getByLabel("API Base URL").fill(apiBase);
    await this.setupDialog().getByLabel("STT Model").fill(model);
  }

  async saveSetup(): Promise<void> {
    await this.setupDialog()
      .getByRole("button", { name: "Connect", exact: true })
      .click();
    await expect(this.setupDialog()).toBeHidden();
  }

  async expectSelected(): Promise<void> {
    await expect(
      this.compatibleCard().getByRole("button", { name: "Current Default" })
    ).toBeVisible();
  }

  async openEdit(): Promise<void> {
    await this.compatibleCard().hover();
    await this.compatibleCard()
      .getByRole("button", { name: "Edit OpenAI-Compatible" })
      .click();
    await expect(this.setupDialog()).toBeVisible();
  }

  async expectSetupValues(apiBase: string, model: string): Promise<void> {
    await expect(this.setupDialog().getByLabel("API Base URL")).toHaveValue(
      apiBase
    );
    await expect(this.setupDialog().getByLabel("STT Model")).toHaveValue(model);
  }

  async updateSetup(apiBase: string, model: string): Promise<void> {
    await this.setupDialog().getByLabel("API Base URL").fill(apiBase);
    await this.setupDialog().getByLabel("STT Model").fill(model);
    await this.setupDialog().getByRole("button", { name: "Update" }).click();
    await expect(this.setupDialog()).toBeHidden();
  }

  async disconnect(): Promise<void> {
    await this.compatibleCard().hover();
    await this.compatibleCard()
      .getByRole("button", { name: "Disconnect OpenAI-Compatible" })
      .click();
    const dialog = this.page.getByRole("dialog", {
      name: "Disconnect OpenAI-Compatible",
    });
    await dialog.getByRole("button", { name: "Disconnect" }).click();
    await expect(
      this.compatibleCard().getByRole("button", { name: "Connect" })
    ).toBeVisible();
  }
}
