/**
 * Page Object Model for the Onyx Craft Scheduled Tasks surface
 * (/craft/v1/tasks, /craft/v1/tasks/new, /craft/v1/tasks/[id]).
 *
 * Encapsulates all locators and interactions so specs remain declarative.
 */

import { type Page, type Locator, expect } from "@playwright/test";

const TASKS_LIST_PATH = "/craft/v1/tasks";
const NEW_TASK_PATH = "/craft/v1/tasks/new";
const DETAIL_PATH_REGEX = /\/craft\/v1\/tasks\/[^/]+$/;

type IntervalUnit = "minutes" | "hours" | "days";

export class ScheduledTasksPage {
  readonly page: Page;

  readonly newTaskButton: Locator;
  readonly nameInput: Locator;
  readonly promptInput: Locator;
  readonly intervalEveryInput: Locator;
  readonly intervalUnitTrigger: Locator;
  readonly saveButton: Locator;
  readonly runNowButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.newTaskButton = page.getByTestId("new-task-button").first();
    // ScheduleTaskForm wraps the inputs in a container with the testid; the
    // actual editable element is the nested input/textarea.
    this.nameInput = page
      .locator(
        '[data-testid="task-name-input"] input, [data-testid="task-name-input"] textarea'
      )
      .first();
    this.promptInput = page
      .locator(
        '[data-testid="task-prompt-input"] textarea, [data-testid="task-prompt-input"]'
      )
      .first();
    this.intervalEveryInput = page
      .locator('[data-testid="interval-every"] input')
      .first();
    // The interval-unit InputSelect has no test ID; it's the only combobox
    // on the new-task form.
    this.intervalUnitTrigger = page.getByRole("combobox").first();
    this.saveButton = page.getByTestId("save-task");
    this.runNowButton = page.getByTestId("run-now-button");
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  /**
   * Navigate to the tasks list. When the Craft feature flag is off the
   * `/craft` layout redirects to `/app`, so callers should follow this with
   * `expectCraftEnabled()` (or skip the test).
   */
  async gotoList(): Promise<void> {
    await this.page.goto(TASKS_LIST_PATH);
    await this.page.waitForLoadState("networkidle");
  }

  isCraftEnabled(): boolean {
    return new URL(this.page.url()).pathname.startsWith(TASKS_LIST_PATH);
  }

  /**
   * Open the create-task form. Prefers the toolbar "New task" button when
   * present (typical case), falls back to direct navigation when the list
   * is in its empty state and the toolbar button isn't rendered.
   *
   * Uses `count()` instead of `isVisible()` for the branching check — the
   * e2e README disallows `isVisible()` for async state, and `count()` is the
   * sanctioned snapshot read for control-flow decisions.
   */
  async openCreateForm(): Promise<void> {
    if ((await this.newTaskButton.count()) > 0) {
      await this.newTaskButton.click();
    } else {
      await this.page.goto(NEW_TASK_PATH);
    }
    await this.page.waitForLoadState("networkidle");
  }

  // ---------------------------------------------------------------------------
  // Create-task form
  // ---------------------------------------------------------------------------

  async fillName(value: string): Promise<void> {
    await this.nameInput.fill(value);
  }

  async fillPrompt(value: string): Promise<void> {
    await this.promptInput.fill(value);
  }

  async setIntervalEvery(value: number): Promise<void> {
    await this.intervalEveryInput.fill(String(value));
  }

  async selectIntervalUnit(unit: IntervalUnit): Promise<void> {
    await this.intervalUnitTrigger.click();
    await this.page.getByRole("option", { name: unit, exact: true }).click();
  }

  async save(): Promise<void> {
    await this.saveButton.click();
  }

  // ---------------------------------------------------------------------------
  // Detail page
  // ---------------------------------------------------------------------------

  async expectOnDetailPage(): Promise<void> {
    await this.page.waitForURL(DETAIL_PATH_REGEX);
  }

  async expectActiveStatus(): Promise<void> {
    await expect(
      this.page.getByTestId("task-status-ACTIVE").first()
    ).toBeVisible();
  }

  async runNow(): Promise<void> {
    await this.runNowButton.click();
  }

  /**
   * Wait for a run row to reach SUCCEEDED or FAILED. Either outcome proves
   * the dispatcher → executor → run-history wiring is reachable; the smoke
   * just needs a row.
   */
  async expectRunInTerminalState(timeout = 60_000): Promise<void> {
    const terminalRunRow = this.page
      .locator('[data-run-status="SUCCEEDED"], [data-run-status="FAILED"]')
      .first();
    await expect(terminalRunRow).toBeVisible({ timeout });
  }
}
