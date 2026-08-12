/**
 * Page Object Model for the Onyx Craft Scheduled Tasks surface
 * (/craft/v1/tasks, /craft/v1/tasks/new, /craft/v1/tasks/[id]).
 *
 * Keeps locators and interactions out of declarative specs.
 */

import { type Page, type Locator, expect } from "@playwright/test";
import { appFixture, mcpServerFixture } from "@/lib/skills/__fixtures__/picker";

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
  readonly saveAndRunNowButton: Locator;
  readonly preApprovalPicker: Locator;
  readonly appsGroup: Locator;
  readonly mcpServersGroup: Locator;

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
    this.saveAndRunNowButton = page.getByTestId("save-and-run-now");
    this.preApprovalPicker = page.getByTestId("pre-approval-picker");
    this.appsGroup = page.getByRole("region", { name: "Apps" });
    this.mcpServersGroup = page.getByRole("region", { name: "MCP servers" });
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  /**
   * Navigate to the tasks list. When the Craft feature flag is off the
   * `/craft` layout redirects to `/app`, so callers should follow this with
   * `isCraftEnabled()` (and `test.skip` if false).
   */
  async gotoList(): Promise<void> {
    await this.page.goto(TASKS_LIST_PATH);
    await this.page.waitForLoadState("networkidle");
    await this.dismissCraftIntro();
  }

  /**
   * Dismiss the first-visit craft intro if it appeared. Fresh e2e users have
   * no `onyx:craftOnboardingSeen:{userId}` localStorage entry, so the intro
   * dialog auto-opens over any /craft/v1 route and its overlay would swallow
   * every click.
   */
  private async dismissCraftIntro(): Promise<void> {
    const intro = this.page
      .getByRole("dialog")
      .filter({ hasText: "Meet Craft" });
    const appeared = await intro
      .waitFor({ state: "visible", timeout: 3000 })
      .then(() => true)
      .catch(() => false);
    if (appeared) {
      await this.page.keyboard.press("Escape");
      await expect(intro).toBeHidden();
    }
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
   * Click "Save and run now" — creates the task with `run_immediately=true`,
   * which enqueues an immediate run. Redirects to the tasks list.
   */
  async saveAndRunNow(): Promise<void> {
    await this.saveAndRunNowButton.click();
  }

  async mockPreApprovalOptions(): Promise<void> {
    await this.page.route("**/api/build/apps", async (route) => {
      await route.fulfill({
        json: [
          appFixture({
            id: 11,
            name: "Acme CRM",
            app_type: "CUSTOM",
          }),
          appFixture({
            id: 12,
            name: "Acme Support",
            app_type: "CUSTOM",
          }),
        ],
      });
    });
    await this.page.route("**/api/mcp/servers/craft", async (route) => {
      await route.fulfill({
        json: {
          mcp_servers: [
            mcpServerFixture({
              id: 22,
              name: "Acme MCP",
              server_url: "https://mcp.example.com/mcp",
            }),
          ],
        },
      });
    });
  }

  async expectResponsivePreApprovalLayout(): Promise<void> {
    await expect(this.preApprovalPicker).toBeVisible();
    await expect(this.appsGroup).toBeVisible();
    await expect(this.mcpServersGroup).toBeVisible();
    await this.expectPreApprovalGroupsFillContainer();

    const appOptions = this.appsGroup.getByTestId(/^pre-approval-app-/);
    await expect(appOptions).toHaveCount(2);
    await expect
      .poll(async () => {
        const [first, second] = await Promise.all([
          appOptions.nth(0).boundingBox(),
          appOptions.nth(1).boundingBox(),
        ]);
        return Boolean(
          first &&
          second &&
          Math.abs(first.y - second.y) <= 1 &&
          second.x > first.x
        );
      })
      .toBe(true);

    await this.page.setViewportSize({ width: 390, height: 844 });
    await this.expectPreApprovalGroupsFillContainer();
    await expect
      .poll(async () => {
        const [first, second] = await Promise.all([
          appOptions.nth(0).boundingBox(),
          appOptions.nth(1).boundingBox(),
        ]);
        return Boolean(
          first &&
          second &&
          Math.abs(first.x - second.x) <= 1 &&
          second.y > first.y
        );
      })
      .toBe(true);
  }

  private async expectPreApprovalGroupsFillContainer(): Promise<void> {
    const container = this.preApprovalPicker.locator("..");
    await expect
      .poll(async () => {
        const [containerBox, pickerBox, appsBox, mcpBox] = await Promise.all([
          container.boundingBox(),
          this.preApprovalPicker.boundingBox(),
          this.appsGroup.boundingBox(),
          this.mcpServersGroup.boundingBox(),
        ]);
        if (!containerBox || !pickerBox || !appsBox || !mcpBox) return false;

        return (
          Math.abs(containerBox.width - pickerBox.width) <= 1 &&
          Math.abs(pickerBox.width - appsBox.width) <= 1 &&
          Math.abs(pickerBox.width - mcpBox.width) <= 1
        );
      })
      .toBe(true);
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

  /**
   * Wait for a run row to reach a terminal state. SUCCEEDED, FAILED, and
   * SKIPPED all qualify — any of them prove the dispatcher → executor →
   * run-history wiring is reachable end-to-end. (SKIPPED is the deterministic
   * outcome when a concurrent provisioner doesn't finish within the wait
   * window, e.g. `sandbox_provisioning`.)
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
