import { expect, type Locator, type Page } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export class AdminImageGenerationPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(): Promise<void> {
    await this.page.goto(ADMIN_ROUTES.IMAGE_GENERATION.path);
    await expect(this.page.getByText("Available Models").first()).toBeVisible({
      timeout: 20000,
    });
  }

  providerTitle(name: string): Locator {
    return this.page.getByText(name, { exact: true });
  }

  modelCard(llmProviderId: number, modelName: string): Locator {
    return this.page.getByLabel(
      `image-gen-model-${llmProviderId}-${modelName}`,
      { exact: true }
    );
  }

  get recommendedTab(): Locator {
    return this.page.getByRole("tab", { name: "Recommended" });
  }

  get allTab(): Locator {
    return this.page.getByRole("tab", { name: "All" });
  }

  get dialog(): Locator {
    return this.page.getByRole("dialog");
  }

  async connect(card: Locator): Promise<void> {
    await card.getByRole("button", { name: "Connect" }).click();
  }

  currentDefaultBadge(card: Locator): Locator {
    return card.getByText("Default", { exact: true });
  }
}
