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
    await scheduledTasks.save();

    await scheduledTasks.expectOnDetailPage();
    await scheduledTasks.expectActiveStatus();

    await scheduledTasks.runNow();
    await scheduledTasks.expectRunInTerminalState();
  });
});
