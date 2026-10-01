import { test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { FlowsPage } from "@tests/e2e/pages/FlowsPage";
import { seedDelayedRun } from "@tests/e2e/utils/flows";

/**
 * Waiting on the clock, and narrowing a list.
 *
 * The delay's whole point is that an hour-long wait costs nothing while it
 * waits, so the run view has to explain a run that is doing nothing on
 * purpose — otherwise it reads as stuck. Nothing here sits through a delay.
 */
test.describe("Flows delay and filter steps", () => {
  test("a run waiting on a delay says so and says until when", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const seeded = await seedDelayedRun(
      page.request,
      `E2E delay ${Date.now()}`
    );

    const flows = new FlowsPage(page);
    await flows.gotoRun(seeded.flowId, seeded.runId);

    await flows.expectRunStatus("AWAITING_DELAY");
    await flows.expectResumeTimeShown();

    // The filter ran before the wait; the step after it has not.
    await flows.expectStepOutcome("keep", "succeeded");
    await flows.expectStepNotRun("after");

    // And it kept the two open rows out of three.
    await flows.selectStepInRun("keep");
    await flows.expectRunPanelContains('"kept": 2');
    await flows.expectRunPanelContains('"dropped": 1');
  });

  test("the editor says whether a delay waits or parks the run", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    await flows.addStep("Delay");
    await flows.selectNode("delay");

    // A minute is the line, and the default sits on the waiting side of it.
    await flows.expectFieldValue("Wait (seconds)", "60");
    await flows.expectInspectorContains("waits where it is");

    await flows.fillField("Wait (seconds)", "3600");
    await flows.expectInspectorContains("put aside");
  });

  test("a filter only asks for a value when the operator needs one", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    await flows.addStep("Filter");
    await flows.selectNode("filter");

    await flows.fillField("List to filter", "{{ steps.http.body.rows }}");
    await flows.fillField("For each item, compare", "{{ item.state }}");
    // The help spells the syntax the field takes, braces and all.
    await flows.expectInspectorContains("{{ item }} and {{ index }}");
    await flows.expectField("Matching value");

    await flows.selectOperator("is not empty");
    await flows.expectNoField("Matching value");

    // Saving is the real check: the server parses the spec and rejects
    // anything it cannot execute.
    await flows.save();
    await flows.reload();
    await flows.expectStepCount(2);
    await flows.selectNode("filter");
    await flows.expectFieldValue("For each item, compare", "{{ item.state }}");
  });
});
