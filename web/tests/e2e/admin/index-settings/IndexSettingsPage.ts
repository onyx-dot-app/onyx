/**
 * Page Object Model for the Admin Index Settings page
 * (/admin/index-settings).
 *
 * Encapsulates model selection, apply actions, and provider setup dialogs.
 */

import { type Page, type Locator, expect } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const INDEX_SETTINGS_URL = ADMIN_ROUTES.INDEX_SETTINGS.path;

export class IndexSettingsPage {
  readonly page: Page;

  readonly pageTitle: Locator;
  readonly viewAllModelsButton: Locator;
  readonly cloudTab: Locator;
  readonly selfHostedTab: Locator;
  readonly applyReindexButton: Locator;
  readonly applyWithoutReindexButton: Locator;
  readonly revertButton: Locator;
  readonly applyContextualModelForwardButton: Locator;
  readonly rebuildExistingDocumentsButton: Locator;
  /** The apply strategy dropdown in the changes banner. */
  readonly strategySelect: Locator;
  readonly imageProcessingSwitch: Locator;
  readonly noModelSelectedWarning: Locator;

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
    this.applyContextualModelForwardButton = page.getByRole("button", {
      name: "Apply to new and updated documents",
    });
    this.rebuildExistingDocumentsButton = page.getByRole("button", {
      name: "Rebuild all existing documents",
    });
    this.applyWithoutReindexButton = page.getByRole("button", {
      name: "Apply without Re-index",
    });
    this.revertButton = page.getByRole("button", { name: "Revert" });
    // Opal's select is a combobox named by its placeholder; its value is
    // the chosen option's title.
    this.strategySelect = page.getByRole("combobox", {
      name: "Select a switchover strategy",
    });
    this.imageProcessingSwitch = page.getByRole("switch", {
      name: /extract & caption images/i,
    });
    this.noModelSelectedWarning = page.getByText("No model selected");
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

  async openGoogleModelSetup(modelName: string): Promise<void> {
    await this.page.getByText(modelName, { exact: true }).click();
    const modal = this.setupModalFor("Google");
    await expect(modal).toBeVisible();
    this.currentSetupModal = modal;
  }

  async fillGoogleWorkloadIdentity(
    projectId: string,
    location: string
  ): Promise<void> {
    await this.activeSetupModal.getByRole("combobox").click();
    await this.page
      .getByRole("option", { name: "Workload Identity (GKE)", exact: true })
      .click();
    await this.activeSetupModal.getByLabel(/GCP Project ID/).fill(projectId);
    await this.activeSetupModal
      .getByLabel(/Google Cloud Region Name/)
      .fill(location);
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

  async stageContextualModel(displayName: string): Promise<void> {
    await this.pickModelInField("Contextual Retrieval LLM", displayName);
  }

  async pickCaptioningModel(displayName: string): Promise<void> {
    await this.pickModelInField("Captioning LLM", displayName);
  }

  /**
   * Open the model picker in the labelled row, search, and choose the row.
   * The list is portalled and carries its own search box, pinned above the
   * listbox rather than inside it; it takes focus as the list opens, which
   * tells it apart from the page's search field. A search unfolds every
   * provider group.
   */
  private async pickModelInField(
    fieldLabel: string,
    displayName: string
  ): Promise<void> {
    await this.page
      .locator("label")
      .filter({ hasText: fieldLabel })
      .getByRole("combobox", { name: "Select model" })
      .click();
    const listbox = this.page.getByRole("listbox", { name: "Select model" });
    await expect(listbox).toBeVisible();
    await this.page
      .getByRole("textbox", { name: "Search" })
      .and(this.page.locator(":focus"))
      .fill(displayName);
    await listbox.getByRole("option", { name: displayName }).click();
  }

  /** Open the contextual model picker and leave it open, touching nothing. */
  async openContextualModelPicker(): Promise<void> {
    await this.page
      .locator("label")
      .filter({ hasText: "Contextual Retrieval LLM" })
      .getByRole("combobox", { name: "Select model" })
      .click();
    await expect(this.modelListbox).toBeVisible();
  }

  /**
   * The open list shows its selection without help: the selected row is on
   * screen and, when the list is long enough to scroll, its first row is not.
   */
  async expectPickerOpenedOnSelection(): Promise<void> {
    await expect(
      this.modelListbox.getByRole("option", { selected: true })
    ).toBeInViewport();
    await expect(
      this.modelListbox.getByRole("option").first()
    ).not.toBeInViewport();
  }

  private get modelListbox(): Locator {
    return this.page.getByRole("listbox", { name: "Select model" });
  }

  // ---------------------------------------------------------------------------
  // Vector quantization
  // ---------------------------------------------------------------------------

  /** Pick a Vector Quantization level by its option title, e.g. "1-bit". */
  async selectVectorQuantization(label: string): Promise<void> {
    await this.page
      .locator("label")
      .filter({ hasText: "Vector Quantization" })
      .getByRole("combobox")
      .click();
    await this.page
      .getByRole("listbox", { name: "Select an option" })
      .getByRole("option", { name: label })
      .click();
  }

  // ---------------------------------------------------------------------------
  // Apply strategy
  // ---------------------------------------------------------------------------

  async selectStrategy(label: string): Promise<void> {
    await this.strategySelect.click();
    await this.page
      .getByRole("listbox", { name: "Select a switchover strategy" })
      .getByRole("option", { name: label })
      .click();
  }

  async expectStrategy(label: RegExp): Promise<void> {
    await expect(this.strategySelect).toHaveValue(label);
  }

  /** Opens the dropdown, asserts the option is not offered, and closes it. */
  async expectStrategyOptionAbsent(label: string): Promise<void> {
    await this.strategySelect.click();
    const listbox = this.page.getByRole("listbox", {
      name: "Select a switchover strategy",
    });
    await expect(listbox.getByRole("option").first()).toBeVisible();
    await expect(listbox.getByRole("option", { name: label })).toHaveCount(0);
    await this.page.keyboard.press("Escape");
  }

  async expectBannerTitle(title: string): Promise<void> {
    await expect(this.page.getByText(title, { exact: true })).toBeVisible();
  }

  async expectContextualModelActions(): Promise<void> {
    await expect(this.applyContextualModelForwardButton).toBeVisible();
    await expect(this.rebuildExistingDocumentsButton).toBeVisible();
  }

  async openForwardOnlyConfirmation(): Promise<void> {
    await this.applyContextualModelForwardButton.click();
    await expect(this.forwardOnlyDialog).toBeVisible();
  }

  async expectForwardOnlyWarning(): Promise<void> {
    await expect(this.forwardOnlyDialog).toContainText(
      "Existing documents will keep context generated by the previous model"
    );
  }

  async confirmForwardOnlyUpdate(): Promise<void> {
    await this.forwardOnlyDialog
      .getByRole("button", {
        name: "Apply to new and updated documents",
      })
      .click();
  }

  private get forwardOnlyDialog(): Locator {
    return this.page.getByRole("dialog", {
      name: "Apply Contextual Retrieval LLM going forward",
    });
  }
}
