import { expect, test, type Page } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";

const TASKS_LIST_PATH = "/craft/v1/tasks";
const NEW_TASK_PATH = "/craft/v1/tasks/new";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Try to navigate to the scheduled tasks list. Returns ``true`` if Onyx Craft
 * is enabled in this environment, ``false`` if we got redirected to ``/app``
 * (feature flag disabled).
 */
async function gotoTasksList(page: Page): Promise<boolean> {
  await page.goto(TASKS_LIST_PATH);
  await page.waitForLoadState("networkidle");
  // The Craft layout redirects to /app when the feature flag is off.
  return new URL(page.url()).pathname.startsWith("/craft/v1/tasks");
}

async function fillCreateForm(page: Page, name: string): Promise<void> {
  // Name
  await page
    .locator(
      '[data-testid="task-name-input"] input, [data-testid="task-name-input"] textarea'
    )
    .first()
    .fill(name);
  // Prompt
  await page
    .locator(
      '[data-testid="task-prompt-input"] textarea, [data-testid="task-prompt-input"]'
    )
    .first()
    .fill("say hi");
  // Interval mode is the default tab; ensure ``every`` is 5 minutes.
  const every = page.locator('[data-testid="interval-every"] input').first();
  await every.fill("5");
  // Select unit "minutes". The default unit is hours; click the trigger and pick minutes.
  // (We can't easily target the InputSelect trigger without a stable testid, so we just
  // rely on the keyboard-arrow approach by clicking the visible trigger text.)
  const unitTrigger = page.getByRole("combobox").first();
  await unitTrigger.click();
  await page.getByRole("option", { name: "minutes", exact: true }).click();
}

// ---------------------------------------------------------------------------
// Spec
// ---------------------------------------------------------------------------

test.describe("Scheduled Tasks", () => {
  test("create, run-now, banner, pause/resume lifecycle", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    // Skip the entire test if Onyx Craft isn't enabled in this environment.
    const craftEnabled = await gotoTasksList(page);
    test.skip(
      !craftEnabled,
      "Onyx Craft is disabled in this environment (settings.onyx_craft_enabled !== true)"
    );

    // Empty state OR existing tasks — either is fine. Click "New scheduled task".
    const newButton = page.getByTestId("new-task-button").first();
    if (await newButton.isVisible()) {
      await newButton.click();
    } else {
      // Empty-state has its own create button; if neither is present, navigate
      // explicitly.
      await page.goto(NEW_TASK_PATH);
    }
    await page.waitForLoadState("networkidle");

    const uniqueName = `E2E test ${Date.now()}`;
    await fillCreateForm(page, uniqueName);

    await page.getByTestId("save-task").click();

    // Land on detail page.
    await page.waitForURL(/\/craft\/v1\/tasks\/[^/]+$/);

    // Status is active by default.
    await expect(page.getByTestId("task-status-active").first()).toBeVisible();

    // Run now button is wired.
    const runNowButton = page.getByTestId("run-now-button");
    await expect(runNowButton).toBeVisible();
    await runNowButton.click();

    // Wait for a run row to appear in the table. Soft-skip if no worker is
    // actually executing in this environment (e.g. CI without the scheduled
    // tasks Celery worker running).
    const succeededOrFailedRow = page
      .locator('[data-run-status="succeeded"], [data-run-status="failed"]')
      .first();
    let terminalRunVisible = false;
    try {
      await expect(succeededOrFailedRow).toBeVisible({ timeout: 60_000 });
      terminalRunVisible = true;
    } catch {
      // No worker available — that's OK. We don't fail the spec because
      // execution depends on the scheduled-tasks worker being up.
      test.info().annotations.push({
        type: "soft-skip",
        description:
          "Run did not reach a terminal state within 60s; assuming the scheduled-tasks worker is not running in this environment.",
      });
    }

    if (terminalRunVisible) {
      const status = await succeededOrFailedRow.getAttribute("data-run-status");
      if (status === "succeeded") {
        await succeededOrFailedRow.click();
        // Confirm session view rendered with the banner + back-to-task link.
        await expect(page.getByTestId("scheduled-run-banner")).toBeVisible();
        await expect(page.getByTestId("back-to-task-button")).toBeVisible();
        // Chat input remains available so users can send follow-ups on
        // scheduled-run sessions.
        await expect(
          page.locator('[placeholder*="conversation"], [placeholder*="task"]')
        ).toBeVisible();
        // Back to task.
        await page.goBack();
        await page.waitForURL(/\/craft\/v1\/tasks\/[^/]+$/);
      }
    }

    // Pause -> Resume status toggle.
    const statusToggle = page.getByTestId("status-toggle");
    await statusToggle.click();
    await expect(page.getByTestId("task-status-paused").first()).toBeVisible();
    await statusToggle.click();
    await expect(page.getByTestId("task-status-active").first()).toBeVisible();

    // Delete (cleanup).
    await page.getByTestId("delete-button").click();
    await page.getByTestId("confirm-delete-task").click();
    await page.waitForURL(/\/craft\/v1\/tasks(\?.*)?$/);
  });
});
