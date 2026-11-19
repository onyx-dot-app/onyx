import { type Locator, type Page, expect } from "@playwright/test";
import type { UploadFile } from "@tests/e2e/utils/plugins";

export class CustomizePluginPage {
  readonly page: Page;
  readonly uploadDialog: Locator;

  constructor(page: Page) {
    this.page = page;
    this.uploadDialog = page.getByRole("dialog", { name: "Upload Plugin" });
  }

  async openUploadDialog(): Promise<void> {
    await this.page.goto("/app/customize/plugins");
    await this.page.getByRole("button", { name: "Add", exact: true }).click();
    await this.page
      .getByRole("menuitem", { name: "Upload plugin", exact: true })
      .click();
    await expect(this.uploadDialog).toBeVisible();
  }

  async chooseZip(file: UploadFile): Promise<void> {
    await this.uploadDialog
      .getByTestId("skill-bundle-dropzone")
      .locator('input[type="file"]')
      .setInputFiles(file);
  }

  async expectSaveLine(text: string): Promise<void> {
    await expect(
      this.uploadDialog.getByText(text, { exact: true })
    ).toBeVisible();
  }

  async expectPreviewText(text: string): Promise<void> {
    await expect(
      this.uploadDialog.getByText(text, { exact: true }).first()
    ).toBeVisible();
  }

  async expectUploadError(text: string | RegExp): Promise<void> {
    await expect(this.uploadDialog.getByRole("alert")).toContainText(text);
  }

  async setSaveAsNew(checked: boolean): Promise<void> {
    const response = this.page.waitForResponse(
      (candidate) =>
        new URL(candidate.url()).pathname === "/api/skills/plugins/inspect"
    );
    await this.uploadDialog
      .getByRole("checkbox", { name: "Save as a New Plugin" })
      .setChecked(checked);
    expect((await response).ok()).toBeTruthy();
  }

  async saveUpload(): Promise<string> {
    const response = this.page.waitForResponse(
      (candidate) =>
        new URL(candidate.url()).pathname === "/api/skills/plugins" &&
        candidate.request().method() === "POST"
    );
    await this.uploadDialog
      .getByRole("button", { name: "Save", exact: true })
      .click();
    const saved = await response;
    expect(saved.ok(), await saved.text()).toBeTruthy();
    const body: { plugin: { id: string } } = await saved.json();
    await expect(this.uploadDialog).toBeHidden();
    await expect(this.page).toHaveURL(
      new RegExp(`/app/customize/plugins/${body.plugin.id}`)
    );
    return body.plugin.id;
  }

  async goto(pluginId: string, tab?: "integrations" | "skills"): Promise<void> {
    await this.page.goto(
      `/app/customize/plugins/${pluginId}${tab ? `?tab=${tab}` : ""}`
    );
  }

  async openTab(prefix: "Skills" | "Integrations"): Promise<void> {
    const tab = this.page.getByRole("tab", { name: new RegExp(`^${prefix}`) });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
  }

  async expectTab(name: string): Promise<void> {
    await expect(
      this.page.getByRole("tab", { name, exact: true })
    ).toBeVisible();
  }

  needRow(name: string): Locator {
    return this.page.getByLabel(name, { exact: true });
  }

  async expectNeed(name: string, state: string, note?: string): Promise<void> {
    const row = this.needRow(name);
    await expect(row.getByText(state, { exact: true })).toBeVisible();
    if (note) await expect(row.getByText(note, { exact: true })).toBeVisible();
  }

  async expectNeedButton(name: string, button: RegExp): Promise<void> {
    await expect(
      this.needRow(name).getByRole("button", { name: button })
    ).toBeVisible();
  }

  async turnOnNeed(name: string): Promise<void> {
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/integrations\/\d+\/enabled$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "PUT"
    );
    await this.needRow(name)
      .getByRole("button", { name: `Turn on ${name}`, exact: true })
      .click();
    expect((await response).ok()).toBeTruthy();
  }

  async addNeedForTeam(name: string): Promise<void> {
    await this.needRow(name)
      .getByRole("button", { name: `Add ${name} for your team`, exact: true })
      .click();
    await expect(this.page).toHaveURL(/\/app\/customize\/integrations\/new\?/);
  }
}
