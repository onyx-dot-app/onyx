/**
 * Page Object Model for the Onyx Craft Scheduled Tasks surface
 * (/craft/v1/tasks, /craft/v1/tasks/new, /craft/v1/tasks/[id]).
 *
 * Keeps locators and interactions out of declarative specs.
 */

import { type Page, type Locator, expect } from "@playwright/test";
import type { AppActionPoliciesView } from "@/lib/plugins/types";
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
  readonly appPolicies: Locator;
  readonly appCards: Locator;

  constructor(page: Page) {
    this.page = page;
    this.newTaskButton = page.getByTestId("new-task-button").first();
    // The InputTypeIn/InputTextArea components spread props directly onto the
    // underlying <input>/<textarea>, so the test IDs land on the editable
    // element itself — not on a wrapper.
    this.nameInput = page.getByTestId("task-name-input");
    this.promptInput = page.getByTestId("task-prompt-input");
    this.intervalEveryInput = page.getByTestId("interval-every");
    // The interval-unit select has no test ID; it's the only combobox
    // on the new-task form.
    this.intervalUnitTrigger = page.getByRole("combobox").first();
    this.saveAndRunNowButton = page.getByTestId("save-and-run-now");
    this.appPolicies = page.locator("section").filter({
      has: page.getByRole("switch", { name: "Enable Acme CRM for this task" }),
    });
    this.appCards = this.appPolicies.getByRole("group");
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

  async mockActionPolicyOptions(): Promise<void> {
    const policies: AppActionPoliciesView[] = [
      { id: 11, name: "Acme CRM", kind: "external_app" as const },
      { id: 12, name: "Acme Support", kind: "external_app" as const },
      { id: 22, name: "Acme MCP", kind: "mcp_server" as const },
    ].map(({ id, name, kind }) => ({
      gated_app_id: id,
      target_id: id,
      name,
      kind,
      enabled: null,
      users_can_manage_policies: true,
      actions: [
        {
          action_id: "send",
          normalised_name: "Send message",
          description: "Send a message.",
          effective_policy: "ASK",
          workspace_policy: "ASK",
          stored_policy: null,
          editable: true,
          lock_reason: null,
        },
      ],
    }));
    await this.page.route("**/api/build/action-policies", async (route) => {
      await route.fulfill({ json: policies });
    });
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

  async expectResponsiveActionPolicyLayout(): Promise<void> {
    await expect(this.appCards).toHaveCount(3);
    for (const name of ["Acme CRM", "Acme Support", "Acme MCP"]) {
      await expect(
        this.appPolicies.getByRole("switch", {
          name: `Enable ${name} for this task`,
        })
      ).not.toBeChecked();
    }
    await expect(
      this.appPolicies.getByRole("button", { name: "Manage actions" })
    ).toHaveCount(0);
    await this.expectActionPolicyCardsFillForm();
    await expect
      .poll(async () => {
        const [first, second] = await Promise.all([
          this.appCards.nth(0).boundingBox(),
          this.appCards.nth(1).boundingBox(),
        ]);
        return Boolean(
          first &&
          second &&
          Math.abs(first.x - second.x) <= 1 &&
          second.y > first.y
        );
      })
      .toBe(true);

    await this.appPolicies
      .getByRole("switch", { name: "Enable Acme CRM for this task" })
      .click();
    await this.appPolicies
      .getByRole("button", { name: "Manage actions" })
      .click();
    const modal = this.page.getByRole("dialog");
    await expect(
      modal.getByRole("group", { name: "Send message" })
    ).toBeVisible();
    await modal.getByRole("button", { name: "Cancel", exact: true }).click();

    await this.page.setViewportSize({ width: 390, height: 844 });
    await this.expectActionPolicyCardsFillForm();
    await expect
      .poll(async () => {
        const [first, second] = await Promise.all([
          this.appCards.nth(0).boundingBox(),
          this.appCards.nth(1).boundingBox(),
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

  private async expectActionPolicyCardsFillForm(): Promise<void> {
    await expect
      .poll(async () => {
        const [container, section, first, second] = await Promise.all([
          this.appPolicies.locator("..").boundingBox(),
          this.appPolicies.boundingBox(),
          this.appCards.nth(0).boundingBox(),
          this.appCards.nth(1).boundingBox(),
        ]);
        if (!container || !section || !first || !second) return false;
        const right = Math.max(first.x + first.width, second.x + second.width);
        return (
          Math.abs(container.width - section.width) <= 1 &&
          Math.abs(section.x - first.x) <= 1 &&
          Math.abs(section.x + section.width - right) <= 1
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
      this.page
        .getByLabel("admin-page-title")
        .getByText("Active", { exact: true })
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
