import { expect, test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { FlowsPage } from "@tests/e2e/pages/FlowsPage";
import { SWITCH_ROUTES, seedSwitchRun } from "@tests/e2e/utils/flows";

/**
 * Routing a run down one of several branches.
 *
 * A switch is the first step whose branches the editor lets you point by
 * hand, so the pickers are most of what is worth pinning: they must offer
 * every step that could follow, never one that came before, and what they
 * pick has to survive the server parsing it.
 */
test.describe("Flows switch step", () => {
  test("each case is pointed at its own step, and the canvas says which", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    await flows.addStep("Switch");

    // Three loose steps for the branches to reach.
    await flows.clickEmptyCanvas();
    await flows.addStep("Transform");
    await flows.clickEmptyCanvas();
    await flows.addStep("Transform");
    await flows.clickEmptyCanvas();
    await flows.addStep("Transform");
    await flows.expectStepUnreachable("transform_3");

    await flows.selectNode("switch");
    // Pointing a branch back at `http` would close a loop, and pointing it
    // at the switch itself is the same mistake in one step.
    expect(await flows.readBranchTargets("Case 1 goes to")).toEqual([
      "End here",
      "transform",
      "transform_2",
      "transform_3",
    ]);

    await flows.fillField("Value to check", "{{ trigger.priority }}");
    await flows.fillCase(1, "high");
    await flows.chooseBranchTarget("Case 1 goes to", "transform");
    await flows.addCase();
    await flows.fillCase(2, "low");
    await flows.chooseBranchTarget("Case 2 goes to", "transform_2");
    await flows.chooseBranchTarget(
      "When nothing matches, go to",
      "transform_3"
    );

    await flows.expectStepConnected("transform_3");
    expect(await flows.readEdgeLabels()).toEqual(["high", "low", "otherwise"]);

    // Saving is the real check: the server parses the spec and refuses a
    // blank case, a repeated one, or a branch that loops back.
    await flows.save();
    await flows.reload();

    expect(await flows.readEdgeLabels()).toEqual(["high", "low", "otherwise"]);
    await flows.selectNode("switch");
    await flows.expectFieldValue("Case 1 value", "high");
    await flows.expectFieldValue("Case 2 value", "low");
    await expect(flows.branchPicker("Case 2 goes to")).toContainText(
      "transform_2"
    );

    // Routing per item has no answer once the items disagree, so the field
    // is not offered. A transform has it, which keeps this honest.
    await flows.expectNoField("Run once per item in");
    await flows.selectNode("transform");
    await flows.expectField("Run once per item in");
  });

  test("a run takes the case that matches and skips the others", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const { flowId, runId } = await seedSwitchRun(
      page.request,
      `Switch run ${Date.now()}`,
      "low"
    );

    const flows = new FlowsPage(page);
    await flows.gotoRun(flowId, runId);
    await flows.expectRunStatus("SUCCEEDED");

    await flows.expectStepOutcome("route", "succeeded");
    await flows.expectStepOutcome(SWITCH_ROUTES.low, "succeeded");
    await flows.expectStepDimmed(SWITCH_ROUTES.high);
    await flows.expectStepDimmed(SWITCH_ROUTES.otherwise);
    await flows.expectStepNotDimmed(SWITCH_ROUTES.low);

    // The row records which case won by position, which is what a resumed
    // run reads to take the same branch again.
    await flows.selectStepInRun("route");
    await flows.expectRunPanelContains('"case": 1');
  });

  test("a value no case expects goes the catch-all way", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const { flowId, runId } = await seedSwitchRun(
      page.request,
      `Switch fallthrough ${Date.now()}`,
      "urgent"
    );

    const flows = new FlowsPage(page);
    await flows.gotoRun(flowId, runId);
    await flows.expectRunStatus("SUCCEEDED");

    await flows.expectStepOutcome(SWITCH_ROUTES.otherwise, "succeeded");
    await flows.expectStepDimmed(SWITCH_ROUTES.high);
    await flows.expectStepDimmed(SWITCH_ROUTES.low);

    await flows.selectStepInRun("route");
    await flows.expectRunPanelContains('"case": null');
  });
});
