/**
 * Page Object Model for the connector edit form
 * (/admin/connectors/{source}/edit/{ccPairId}) and its plan preview.
 */

import { type Locator, type Page, expect } from "@playwright/test";

export class ConnectorEditPage {
  readonly page: Page;
  readonly nameInput: Locator;
  readonly reviewButton: Locator;
  readonly addFilesButton: Locator;
  readonly planModal: Locator;
  readonly applyButton: Locator;
  readonly replanButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.nameInput = page.getByTestId("connector-name");
    this.reviewButton = page.getByRole("button", {
      name: "Review changes",
      exact: true,
    });
    this.addFilesButton = page.getByRole("button", {
      name: "Add files",
      exact: true,
    });
    this.planModal = page.getByTestId("edit-plan-modal");
    this.applyButton = this.planModal.getByRole("button", {
      name: "Apply",
      exact: true,
    });
    this.replanButton = this.planModal.getByRole("button", {
      name: "Plan again",
      exact: true,
    });
  }

  async goto(source: string, ccPairId: number): Promise<void> {
    await this.page.goto(`/admin/connectors/${source}/edit/${ccPairId}`);
  }

  async expectLoaded(connectorName: string): Promise<void> {
    await expect(
      this.page.getByText(`Edit ${connectorName}`, { exact: true })
    ).toBeVisible({ timeout: 30000 });
    await expect(this.nameInput).toHaveValue(connectorName);
  }

  async setName(name: string): Promise<void> {
    await this.nameInput.fill(name);
    await this.nameInput.blur();
  }

  /** Uploads a text file; it is staged for the edit and listed. */
  async addFile(fileName: string, content: string): Promise<void> {
    const fileChooserPromise = this.page.waitForEvent("filechooser");
    await this.addFilesButton.click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles({
      name: fileName,
      mimeType: "text/plain",
      buffer: Buffer.from(content, "utf-8"),
    });
    await expect(this.page.getByText(fileName, { exact: true })).toBeVisible({
      timeout: 30000,
    });
  }

  async reviewChanges(): Promise<void> {
    await expect(this.reviewButton).toBeEnabled({ timeout: 30000 });
    await this.reviewButton.click();
    await expect(this.planModal).toBeVisible({ timeout: 30000 });
  }

  async expectPlanChanges(text: string | RegExp): Promise<void> {
    await expect(this.planModal.getByText(text)).toBeVisible();
  }

  async expectPlanStep(kind: string): Promise<void> {
    await expect(
      this.planModal.getByTestId(`edit-plan-step-${kind}`)
    ).toBeVisible();
  }

  async apply(): Promise<void> {
    await expect(this.applyButton).toBeEnabled();
    await this.applyButton.click();
  }

  async expectApplied(ccPairId: number): Promise<void> {
    await expect(this.page.getByText("The changes are applied.")).toBeVisible({
      timeout: 30000,
    });
    await expect(this.page).toHaveURL(
      new RegExp(`/admin/connector/${ccPairId}$`)
    );
  }
}
