import { expect, type Page } from "@playwright/test";

export class UsageReportsPage {
  constructor(readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/admin/performance/analytics");
  }

  async reload(): Promise<void> {
    await this.page.reload();
  }

  // Client-side navigation keeps the SWR cache, unlike a reload.
  async leave(): Promise<void> {
    await this.page.locator("a[href='/admin/agents']").first().click();
    await this.page.waitForURL("**/admin/agents");
    await expect(
      this.page.getByRole("button", { name: "Generate report", exact: true })
    ).toBeHidden();
  }

  async goBack(): Promise<void> {
    await this.page.goBack();
  }

  async expectPendingRow(): Promise<void> {
    await expect(this.page.getByTestId("pending-report-row")).toBeVisible();
  }

  async expectGenerating(): Promise<void> {
    await this.expectPendingRow();
    await expect(
      this.page.getByRole("button", { name: "Generating…" })
    ).toBeDisabled();
  }

  async generateReport(): Promise<void> {
    await this.page
      .getByRole("button", { name: "Generate report", exact: true })
      .click();
    await this.page.getByRole("menuitem", { name: "All time" }).click();
  }

  async expectCanGenerate(): Promise<void> {
    await expect(
      this.page.getByRole("button", { name: "Generate report", exact: true })
    ).toBeEnabled();
  }

  async expectFailure(): Promise<void> {
    await expect(
      this.page.getByText("Report generation failed", { exact: true })
    ).toBeVisible();
    await expect(
      this.page.getByRole("button", { name: "Generate report", exact: true })
    ).toBeEnabled();
  }

  async expectReport(period: string): Promise<void> {
    await expect(
      this.page.getByText(period, { exact: true }).first()
    ).toBeVisible();
  }
}
