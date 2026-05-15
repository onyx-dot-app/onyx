/**
 * Page Object Model for the Onyx Craft Scheduled Tasks surface
 * (/craft/v1/tasks, /craft/v1/tasks/new, /craft/v1/tasks/[id]).
 *
 * Encapsulates all locators and interactions so specs remain declarative.
 */

import { type Page, type Locator, expect } from "@playwright/test";

const TASKS_LIST_PATH = "/craft/v1/tasks";
const NEW_TASK_PATH = "/craft/v1/tasks/new";
// `[^/]+` would also match `/new` (the create form), so exclude that segment
// explicitly. Matches any UUID/string except literally "new".
const DETAIL_PATH_REGEX = /\/craft\/v1\/tasks\/(?!new(?:$|\?|\/))[^/]+$/;
const LIST_PATH_REGEX = /\/craft\/v1\/tasks(?:\?|$)/;

type IntervalUnit = "minutes" | "hours" | "days";

export class ScheduledTasksPage {
  readonly page: Page;

  readonly newTaskButton: Locator;
  readonly nameInput: Locator;
  readonly promptInput: Locator;
  readonly intervalEveryInput: Locator;
  readonly intervalUnitTrigger: Locator;
  readonly saveButton: Locator;
  readonly saveAndRunNowButton: Locator;
  readonly runNowButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.newTaskButton = page.getByTestId("new-task-button").first();
    // The InputTypeIn/InputTextArea components spread props directly onto the
    // underlying <input>/<textarea>, so the test IDs land on the editable
    // element itself — not on a wrapper.
    this.nameInput = page.getByTestId("task-name-input");
    this.promptInput = page.getByTestId("task-prompt-input");
    this.intervalEveryInput = page.getByTestId("interval-every");
    // The interval-unit InputSelect has no test ID; it's the only combobox
    // on the new-task form.
    this.intervalUnitTrigger = page.getByRole("combobox").first();
    this.saveButton = page.getByTestId("save-task");
    this.saveAndRunNowButton = page.getByTestId("save-and-run-now");
    this.runNowButton = page.getByTestId("run-now-button");
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  /**
   * Seed the `build_user_persona` cookie so the Craft onboarding modal
   * doesn't intercept the page. Without this, non-admin workers without a
   * pre-existing persona cookie will hit `BuildOnboardingModal` on first
   * navigation, blocking every other interaction. The shape matches
   * `BuildUserPersona` in `web/src/app/craft/onboarding/constants.ts`.
   */
  private async seedBuildPersonaCookie(): Promise<void> {
    const url = new URL(this.page.url());
    const domain = url.hostname || "localhost";
    await this.page.context().addCookies([
      {
        name: "build_user_persona",
        value: encodeURIComponent(
          JSON.stringify({ workArea: "engineering", level: "ic" })
        ),
        domain,
        path: "/",
        expires: Math.floor(Date.now() / 1000) + 60 * 60 * 24 * 365,
      },
    ]);
  }

  /**
   * Navigate to the tasks list. When the Craft feature flag is off the
   * `/craft` layout redirects to `/app`, so callers should follow this with
   * `isCraftEnabled()` (and `test.skip` if false).
   */
  async gotoList(): Promise<void> {
    // Land on the base URL first so we have a real origin for the cookie,
    // then seed the persona cookie, then navigate to the tasks list.
    await this.page.goto("/");
    await this.seedBuildPersonaCookie();
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

  /**
   * Click "Save". The create flow redirects to the tasks list (NOT the
   * detail page), so callers should follow this with `expectOnListPage()`
   * and `openTaskByName()` if they need to reach the detail surface.
   */
  async save(): Promise<void> {
    await this.saveButton.click();
  }

  /**
   * Click "Save and run now" — creates the task with `run_immediately=true`,
   * which enqueues an immediate run. Same redirect as `save()`: lands on
   * the tasks list.
   */
  async saveAndRunNow(): Promise<void> {
    await this.saveAndRunNowButton.click();
  }

  // ---------------------------------------------------------------------------
  // List page
  // ---------------------------------------------------------------------------

  async expectOnListPage(): Promise<void> {
    await this.page.waitForURL(LIST_PATH_REGEX);
  }

  /**
   * Click the row for the task with the given name to navigate to its
   * detail page. Names are unique within a test run (callers should
   * embed a timestamp/uuid).
   */
  async openTaskByName(name: string): Promise<void> {
    await this.page.getByRole("row").filter({ hasText: name }).first().click();
    await this.expectOnDetailPage();
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
   * Wait for a run row to reach a terminal state. SUCCEEDED, FAILED, and
   * SKIPPED all qualify — any of them prove the dispatcher → executor →
   * run-history wiring is reachable end-to-end. (SKIPPED is the deterministic
   * outcome when the sandbox provider is unavailable in dev, e.g.
   * `sandbox_unavailable`.)
   */
  async expectRunInTerminalState(timeout = 60_000): Promise<void> {
    const terminalRunRow = this.page
      .locator(
        '[data-run-status="SUCCEEDED"], [data-run-status="FAILED"], [data-run-status="SKIPPED"]'
      )
      .first();
    await expect(terminalRunRow).toBeVisible({ timeout });
  }
}
