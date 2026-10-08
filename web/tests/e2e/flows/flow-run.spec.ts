import { test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { FlowsPage } from "@tests/e2e/pages/FlowsPage";
import { seedFinishedRun } from "@tests/e2e/utils/flows";

/**
 * The run view draws a finished run on the same canvas as the editor, so the
 * shape you built is the shape you debug.
 *
 * These specs need a worker consuming the `scheduled_tasks` queue. Without
 * one the seeded run never leaves QUEUED and `seedFinishedRun` fails with
 * that as the message, rather than the specs failing somewhere confusing
 * further down.
 */
test.describe("Flows run view", () => {
  test("draws each step with the outcome it had", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const seeded = await seedFinishedRun(
      page.request,
      `E2E run view ${Date.now()}`
    );

    const flows = new FlowsPage(page);
    await flows.gotoRun(seeded.flowId, seeded.runId);

    await flows.expectRunStatus("SUCCEEDED");

    // Every step the run reached is ringed by its result.
    await flows.expectStepOutcome("seed", "succeeded");
    await flows.expectStepOutcome("check", "succeeded");
    await flows.expectStepOutcome("expand", "succeeded");
    await flows.expectStepOutcome("summary", "succeeded");

    // The branch the condition did not take is skipped, and reads as muted
    // rather than as a failure — it is the normal outcome, not a problem.
    await flows.expectStepOutcome("quiet", "skipped");
    await flows.expectStepDimmed("quiet");
    await flows.expectStepNotDimmed("seed");
  });

  test("shows what a step took in and gave back", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const seeded = await seedFinishedRun(
      page.request,
      `E2E run inspect ${Date.now()}`
    );

    const flows = new FlowsPage(page);
    await flows.gotoRun(seeded.flowId, seeded.runId);

    // A step that fanned out reports one entry per item, so a run over three
    // rows can be read row by row rather than as one blob.
    await flows.selectStepInRun("expand");
    await flows.expectRunItemCount(3);
    await flows.expectRunPanelContains("issue 101");
    await flows.expectRunPanelContains("issue 103");

    // The per-item input is there too, which is what answers "why did this
    // one come out different".
    await flows.expectRunPanelContains('"index": 0');

    // A step that ran once reports once.
    await flows.selectStepInRun("summary");
    await flows.expectRunItemCount(1);
  });

  test("a test run from the editor lands on its own run", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();

    // A new flow's HTTP step points nowhere, so this run fails — which is
    // the path worth covering: the run view has to explain a failure, not
    // just decorate a success.
    await flows.startTestRun();
    await flows.expectRunStatus("FAILED");
    await flows.expectStepOutcome("http", "failed");

    await flows.selectStepInRun("http");
    await flows.expectRunItemCount(1);
  });
});
