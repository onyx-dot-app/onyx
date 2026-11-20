import { test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { AppScheduledTasksPage } from "@tests/e2e/pages/AppScheduledTasksPage";

// Needs the scheduled_tasks Celery worker; without it runs never finish.
test.describe("Scheduled tasks in chat", () => {
  test("a run opens as a chat and clears its unseen dot", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const tasks = new AppScheduledTasksPage(page);
    const name = `E2E chat task ${Date.now()}`;

    await tasks.gotoList();
    try {
      await tasks.createAndRun(name, "say hi");
      await tasks.expectRunSucceeded();
      await tasks.expectUnseenRun();

      await tasks.openRun();
      await tasks.expectRunBanner(name);

      await tasks.backToTask();
      await tasks.expectRunViewed();
    } finally {
      await tasks.deleteCreatedTask();
    }
  });
});
