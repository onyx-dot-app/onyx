import { expect, test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { FlowsPage } from "@tests/e2e/pages/FlowsPage";
import {
  FIRST_PAGE_QUESTION,
  seedCursorLoopRun,
  seedLoopedApprovalRun,
} from "@tests/e2e/utils/flows";

/**
 * A loop that runs a group of steps again and again until a condition holds.
 *
 * The run view is where a loop has to explain itself: one step, several
 * rows, and the only way to read them is by pass. An approval inside a loop
 * is the hard case — it parks the run once per pass, and every answer has
 * to lead to the next question rather than to the end.
 */
test.describe("Flows loop until", () => {
  test("the first step added after a loop is what it repeats", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    await flows.addStep("Loop (until)");
    await flows.selectNode("repeat");
    await flows.expectInspectorContains(
      "The first step you add after this one becomes what it repeats."
    );

    await flows.addStep("Transform");
    await flows.selectNode("repeat");
    await flows.expectInspectorNotContains("The first step you add");
    await expect(flows.branchPicker("Repeat from")).toContainText("transform");

    // Once it has something to repeat, added steps follow the loop.
    await flows.addStep("Transform");
    await flows.selectNode("repeat");

    await flows.fillField("Stop when", "{{ steps.transform.value }}");
    // Each pass holds the run's budget, so the editor keeps to the server's
    // ceiling.
    await flows.fillField("Most passes", "99");
    await flows.expectFieldValue("Most passes", "50");
    await flows.fillField("Most passes", "5");

    // A loop per item would multiply every pass, so it is not offered.
    await flows.expectNoField("Run once per item in");

    expect(await flows.readEdgeLabels()).toEqual([
      "again",
      "each pass",
      "when done",
    ]);

    // Saving is the real check: the server refuses a loop whose steps can be
    // reached from outside it, or whose next step is also inside it.
    await flows.save();
    await flows.reload();

    expect(await flows.readEdgeLabels()).toEqual([
      "again",
      "each pass",
      "when done",
    ]);
    await flows.selectNode("repeat");
    await expect(flows.branchPicker("Repeat from")).toContainText("transform");
    await flows.expectFieldValue("Stop when", "{{ steps.transform.value }}");
    await flows.expectFieldValue("Most passes", "5");
  });

  test("a run shows each pass of a step on its own", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const { flowId, runId } = await seedCursorLoopRun(
      page.request,
      `Cursor loop ${Date.now()}`
    );

    const flows = new FlowsPage(page);
    await flows.gotoRun(flowId, runId);
    await flows.expectRunStatus("SUCCEEDED");

    await flows.selectStepInRun("read");
    await flows.expectRunItemHeadings(["Pass 1", "Pass 2", "Pass 3"]);

    await flows.selectStepInRun("pages");
    await flows.expectRunPanelContains('"passes": 3');
    await flows.expectRunPanelContains('"satisfied": true');
  });

  test("an approval inside a loop is asked again on every pass", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const { flowId, runId } = await seedLoopedApprovalRun(
      page.request,
      `Looped approval ${Date.now()}`
    );

    const flows = new FlowsPage(page);
    await flows.gotoRun(flowId, runId);
    await flows.expectAwaitingDecision(FIRST_PAGE_QUESTION);

    await flows.decideAndExpectNext("approve", "Send page 2?");
    await flows.decide("approve");
    await flows.expectRunStatus("SUCCEEDED", 60_000);

    await flows.selectStepInRun("send");
    await flows.expectRunItemHeadings(["Pass 1", "Pass 2"]);
  });
});
