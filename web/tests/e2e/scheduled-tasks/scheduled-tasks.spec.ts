import { test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { ScheduledTasksPage } from "@tests/e2e/scheduled-tasks/ScheduledTasksPage";

test.describe("Scheduled Tasks", () => {
  test("create, run, and verify a run row exists", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const scheduledTasks = new ScheduledTasksPage(page);

    await scheduledTasks.gotoList();
    test.skip(
      !scheduledTasks.isCraftEnabled(),
      "Onyx Craft is disabled in this environment (settings.onyx_craft_enabled !== true)"
    );

    await scheduledTasks.openCreateForm();

    const uniqueName = `E2E smoke ${Date.now()}`;
    await scheduledTasks.fillName(uniqueName);
    await scheduledTasks.fillPrompt("say hi");
    await scheduledTasks.setIntervalEvery(5);
    await scheduledTasks.selectIntervalUnit("minutes");

    // "Save and run now" creates the task with run_immediately=true (the
    // dispatcher enqueues a run on creation) and redirects to the list.
    await scheduledTasks.saveAndRunNow();
    await scheduledTasks.expectOnListPage();

    // Navigate to the detail page to see status + run history.
    await scheduledTasks.openTaskByName(uniqueName);
    await scheduledTasks.expectActiveStatus();

    // A run row in a terminal state proves the dispatcher → executor →
    // run-history wiring is reachable end-to-end.
    await scheduledTasks.expectRunInTerminalState();
  });
});
