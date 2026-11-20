import { type Locator, type Page, expect } from "@playwright/test";

export interface MarketplaceSourceInput {
  repository: string;
  folder?: string;
  ref?: string;
}

export class MarketplacesPage {
  readonly page: Page;
  readonly addDialog: Locator;
  readonly table: Locator;

  constructor(page: Page) {
    this.page = page;
    this.addDialog = page.getByRole("dialog", {
      name: /^(Add|Confirm) Marketplace\b/,
    });
    this.table = page.getByRole("table", { name: "Marketplaces" });
  }

  async openAddDialog(): Promise<void> {
    await this.page.goto("/app/customize/plugins");
    await this.page.getByRole("button", { name: "Add", exact: true }).click();
    await this.page
      .getByRole("menuitem", { name: "Add marketplace", exact: true })
      .click();
    await expect(this.addDialog).toBeVisible();
  }

  async enterSource(source: MarketplaceSourceInput): Promise<void> {
    await this.addDialog.getByLabel("Repository").fill(source.repository);
    if (source.folder)
      await this.addDialog.getByLabel("Folder").fill(source.folder);
    if (source.ref)
      await this.addDialog.getByLabel("Branch, Tag or Commit").fill(source.ref);
    await this.addDialog
      .getByRole("button", { name: "Continue", exact: true })
      .click();
    await expect(
      this.page.getByRole("dialog", { name: /^Confirm Marketplace\b/ })
    ).toBeVisible();
  }

  async expectResolved(texts: string[]): Promise<void> {
    for (const text of texts)
      await expect(
        this.addDialog.getByText(text, { exact: true }).first()
      ).toBeVisible();
  }

  async showUnusable(count: number): Promise<void> {
    await this.addDialog
      .getByRole("button", {
        name: `Show ${count} ${count === 1 ? "entry" : "entries"} that Onyx cannot use`,
        exact: true,
      })
      .click();
  }

  async add(): Promise<void> {
    await this.addDialog
      .getByRole("button", { name: "Add marketplace", exact: true })
      .click();
    await expect(this.addDialog).toBeHidden();
  }

  async gotoManage(): Promise<void> {
    await this.page.goto("/app/customize/plugins/marketplaces");
    await expect(
      this.page.getByRole("heading", { name: "Marketplaces" })
    ).toBeVisible();
  }

  row(name: string): Locator {
    return this.table.getByRole("row").filter({ hasText: name });
  }

  async expectRow(name: string, texts: string[]): Promise<void> {
    const row = this.row(name);
    await expect(row).toBeVisible();
    for (const text of texts)
      await expect(row.getByText(text, { exact: true })).toBeVisible();
  }

  async syncNow(name: string): Promise<void> {
    await this.row(name)
      .getByRole("button", { name: `Actions for ${name}`, exact: true })
      .click();
    await this.page
      .getByRole("menuitem", { name: "Sync now", exact: true })
      .click();
  }

  async expectSyncState(name: string, state: string): Promise<void> {
    await expect(
      this.row(name).getByText(state, { exact: true })
    ).toBeVisible();
  }
}
