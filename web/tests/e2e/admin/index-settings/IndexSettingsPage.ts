/**
 * Page Object Model for the Admin Index Settings page
 * (/admin/configuration/index-settings).
 *
 * Encapsulates all locators and interactions for the embedding-model picker
 * and the cloud-provider setup modals so specs stay declarative.
 */

import { type Page, type Locator, expect } from "@playwright/test";

const INDEX_SETTINGS_URL = "/admin/configuration/index-settings";

export class IndexSettingsPage {
  readonly page: Page;

  readonly pageTitle: Locator;
  readonly viewAllModelsButton: Locator;
  readonly cloudTab: Locator;
  readonly selfHostedTab: Locator;
  readonly applyReindexButton: Locator;

  // The provider setup modal opened via `openProviderSetup`. Held so the
  // credential / model-spec fill methods scope their fields to the right
  // dialog without the spec passing the provider name around.
  private currentSetupModal: Locator | null = null;

  constructor(page: Page) {
    this.page = page;
    this.pageTitle = page.getByLabel("admin-page-title");
    this.viewAllModelsButton = page.getByRole("button", {
      name: /view all models/i,
    });
    this.cloudTab = page.getByRole("tab", { name: /cloud.based/i });
    this.selfHostedTab = page.getByRole("tab", { name: /self.hosted/i });
    this.applyReindexButton = page.getByRole("button", {
      name: "Apply & Re-index",
    });
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  async goto(): Promise<void> {
    await this.page.goto(INDEX_SETTINGS_URL);
    await this.page.waitForLoadState("networkidle");
    await expect(this.pageTitle).toHaveText(/index settings/i);
  }

  async expandModelPicker(): Promise<void> {
    await expect(this.viewAllModelsButton).toBeVisible({ timeout: 10000 });
    await this.viewAllModelsButton.click();
  }

  async switchToCloudTab(): Promise<void> {
    await expect(this.cloudTab).toBeVisible({ timeout: 10000 });
    await this.cloudTab.click();
  }

  // ---------------------------------------------------------------------------
  // Cloud-provider setup modal (LiteLLM / Azure — providers with no
  // pre-registered models render an "Add Configuration" card)
  // ---------------------------------------------------------------------------

  private setupModalFor(displayName: string): Locator {
    return this.page.getByRole("dialog", {
      name: new RegExp(`set up ${displayName}`, "i"),
    });
  }

  private get activeSetupModal(): Locator {
    if (!this.currentSetupModal) {
      throw new Error(
        "No provider setup modal is open — call openProviderSetup() first."
      );
    }
    return this.currentSetupModal;
  }

  async openProviderSetup(displayName: string): Promise<void> {
    await this.page
      .getByText(
        new RegExp(
          `add configs for your ${displayName} embedding providers`,
          "i"
        )
      )
      .click();
    const modal = this.setupModalFor(displayName);
    await expect(modal).toBeVisible({ timeout: 10000 });
    this.currentSetupModal = modal;
  }

  // Fields are targeted by input id (which equals the Formik field name) rather
  // than by label: Opal's InputVertical folds each field's subDescription into
  // its accessible name, so a label match like "Deployment Name" also matches
  // the Model Name field whose description mentions "deployment name".

  async fillLiteLLMCredentials(creds: {
    apiBaseUrl: string;
    apiKey: string;
  }): Promise<void> {
    await this.activeSetupModal.locator("#apiUrl").fill(creds.apiBaseUrl);
    await this.activeSetupModal.locator("#apiKey").fill(creds.apiKey);
  }

  async fillAzureCredentials(creds: {
    targetUrl: string;
    apiKey: string;
    apiVersion: string;
    deploymentName: string;
  }): Promise<void> {
    await this.activeSetupModal.locator("#apiUrl").fill(creds.targetUrl);
    await this.activeSetupModal.locator("#apiKey").fill(creds.apiKey);
    await this.activeSetupModal.locator("#apiVersion").fill(creds.apiVersion);
    await this.activeSetupModal
      .locator("#deploymentName")
      .fill(creds.deploymentName);
  }

  async fillModelSpec(spec: {
    modelName: string;
    modelDim: number;
  }): Promise<void> {
    await this.activeSetupModal.locator("#modelName").fill(spec.modelName);
    await this.activeSetupModal
      .locator("#modelDim")
      .fill(String(spec.modelDim));
  }

  /** Submit the open setup modal ("Connect") and wait for it to close. */
  async submitProviderSetup(): Promise<void> {
    const connectButton = this.activeSetupModal.getByRole("button", {
      name: /connect/i,
    });
    await expect(connectButton).toBeEnabled({ timeout: 5000 });
    await connectButton.click();
    await expect(this.activeSetupModal).not.toBeVisible({ timeout: 15000 });
    this.currentSetupModal = null;
  }

  // ---------------------------------------------------------------------------
  // Staging / apply
  // ---------------------------------------------------------------------------

  /** Assert a model has been staged into the form (Apply & Re-index appears). */
  async expectModelStaged(): Promise<void> {
    await expect(this.applyReindexButton).toBeVisible({ timeout: 10000 });
  }

  async applyReindex(): Promise<void> {
    await this.applyReindexButton.click();
  }
}
