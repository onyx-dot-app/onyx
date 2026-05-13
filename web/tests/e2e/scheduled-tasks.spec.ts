import { expect, test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";

const TASKS_LIST_PATH = "/craft/v1/tasks";
const NEW_TASK_PATH = "/craft/v1/tasks/new";

test.describe("Scheduled Tasks", () => {
  test("create, run, and verify a run row exists", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    // The Craft layout redirects to /app when the feature flag is off.
    await page.goto(TASKS_LIST_PATH);
    await page.waitForLoadState("networkidle");
    const craftEnabled = new URL(page.url()).pathname.startsWith(
      "/craft/v1/tasks"
    );
    test.skip(
      !craftEnabled,
      "Onyx Craft is disabled in this environment (settings.onyx_craft_enabled !== true)"
    );

    // Open the create form. Prefer the toolbar button; fall back to the
    // route directly if the list is in its empty state.
    const newButton = page.getByTestId("new-task-button").first();
    if (await newButton.isVisible()) {
      await newButton.click();
    } else {
      await page.goto(NEW_TASK_PATH);
    }
    await page.waitForLoadState("networkidle");

    const uniqueName = `E2E smoke ${Date.now()}`;
    await page
      .locator(
        '[data-testid="task-name-input"] input, [data-testid="task-name-input"] textarea'
      )
      .first()
      .fill(uniqueName);
    await page
      .locator(
        '[data-testid="task-prompt-input"] textarea, [data-testid="task-prompt-input"]'
      )
      .first()
      .fill("say hi");
    await page
      .locator('[data-testid="interval-every"] input')
      .first()
      .fill("5");
    await page.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "minutes", exact: true }).click();

    await page.getByTestId("save-task").click();

    // Task is created → we land on the detail page with an active-status chip.
    await page.waitForURL(/\/craft\/v1\/tasks\/[^/]+$/);
    await expect(page.getByTestId("task-status-active").first()).toBeVisible();

    // Trigger an immediate run.
    await page.getByTestId("run-now-button").click();

    // A run row in a terminal state proves the dispatcher → executor →
    // run-history wiring is reachable end-to-end. Either outcome is OK
    // for the smoke — we just need a row.
    const terminalRunRow = page
      .locator('[data-run-status="succeeded"], [data-run-status="failed"]')
      .first();
    await expect(terminalRunRow).toBeVisible({ timeout: 60_000 });
  });
});
