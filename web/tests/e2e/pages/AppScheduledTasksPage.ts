import { expect, type Locator, type Page } from "@playwright/test";

const LIST_PATH = "/app/scheduled-tasks";
const DETAIL_PATH = /\/app\/scheduled-tasks\/(?!new(?:$|\?))[^/?]+(?:\?.*)?$/;
const RUN_TIMEOUT_MS = 120_000;

/** The scheduled tasks pages under /app and the run banner in chat. */
export class AppScheduledTasksPage {
  readonly page: Page;
  /** The task that `createAndRun` made, for `deleteCreatedTask`. */
  private createdTaskId: string | null = null;

  constructor(page: Page) {
    this.page = page;
  }

  get sidebarTab(): Locator {
    return this.page.getByTestId("AppSidebar/scheduled-tasks");
  }

  get sidebarUnseenMarker(): Locator {
    return this.sidebarTab.getByRole("img", { name: "New results" });
  }

  get runBanner(): Locator {
    return this.page.getByTestId("scheduled-run-banner");
  }

  async gotoList(): Promise<void> {
    await this.page.goto(LIST_PATH);
    await expect(
      this.page.getByTestId("new-scheduled-task").first()
    ).toBeVisible();
  }

  async createAndRun(name: string, prompt: string): Promise<void> {
    await this.page.getByTestId("new-scheduled-task").first().click();
    await this.page.getByTestId("scheduled-task-name").fill(name);
    await this.page.getByTestId("scheduled-task-prompt").fill(prompt);
    const runButton = this.page.getByTestId("save-and-run-scheduled-task");
    await expect(runButton).toBeEnabled();
    await runButton.click();
    await this.page.waitForURL(DETAIL_PATH);
    this.createdTaskId =
      new URL(this.page.url()).pathname.split("/").pop() ?? null;
  }

  /** Delete the task that `createAndRun` made, so its hourly runs do not
   * leave unseen results on the worker account. */
  async deleteCreatedTask(): Promise<void> {
    if (!this.createdTaskId) return;
    const response = await this.page.request.delete(
      `/api/scheduled-tasks/${this.createdTaskId}`
    );
    expect(response.ok()).toBe(true);
    this.createdTaskId = null;
  }

  /** The newest run row once its chat can open. */
  private get finishedRun(): Locator {
    return this.page
      .getByRole("row")
      .filter({ has: this.page.locator('[data-run-status="SUCCEEDED"]') })
      .first();
  }

  async expectRunSucceeded(): Promise<void> {
    await expect(this.finishedRun).toBeVisible({ timeout: RUN_TIMEOUT_MS });
  }

  async expectUnseenRun(): Promise<void> {
    await expect(
      this.finishedRun.getByRole("img", { name: "New results" })
    ).toBeVisible();
    await expect(this.sidebarUnseenMarker).toBeVisible();
  }

  async openRun(): Promise<void> {
    await this.finishedRun.click();
    await this.page.waitForURL(/\/app\?chatId=/);
  }

  async expectRunBanner(taskName: string): Promise<void> {
    await expect(this.runBanner).toContainText(taskName);
  }

  async backToTask(): Promise<void> {
    await this.runBanner.getByRole("link", { name: "View task" }).click();
    await this.page.waitForURL(DETAIL_PATH);
  }

  async expectRunViewed(): Promise<void> {
    await expect(this.sidebarUnseenMarker).toBeHidden();
    await expect(
      this.finishedRun.getByRole("img", { name: "New results" })
    ).toBeHidden();
  }
}
