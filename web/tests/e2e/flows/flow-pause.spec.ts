import { expect, test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { FlowsPage } from "@tests/e2e/pages/FlowsPage";
import {
  PACED_PAUSE_SECONDS,
  readItemGapsMs,
  seedPacedRun,
} from "@tests/e2e/utils/flows";

/**
 * Pausing between batches, for an API that limits how fast it may be called.
 *
 * The pause lives on the step that sends the batches, not on the loop that
 * cuts them, because that step is what waits. So the loop points there, and
 * the setting only exists while its step runs once per item.
 */
test.describe("Flows pause between batches", () => {
  test("a step that runs once per batch can pause between them", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    // Named for what it does, so someone looking for "batch" finds it — in
    // the palette, on the card and at the top of its settings alike.
    await flows.addStep("Loop (batches)");
    await flows.expectStepKind("loop", "Loop (batches)");
    await flows.selectNode("loop");
    await flows.expectInspectorContains("Loop (batches)");
    await flows.fillField("Split this list", "{{ steps.http.body }}");
    await flows.expectInspectorContains("To wait between batches");

    await flows.addStep("Transform");
    await flows.selectNode("transform");

    // A pause sits between items, so there is none to set on a step that
    // runs once.
    await flows.expectNoField("Seconds between items");
    await flows.fillField("Run once per item in", "{{ steps.loop.batches }}");
    await flows.expectFieldValue("Seconds between items", "0");

    // It holds a worker while it waits, so the editor keeps it to what the
    // server allows.
    await flows.fillField("Seconds between items", "999");
    await flows.expectFieldValue("Seconds between items", "60");

    await flows.fillField("Seconds between items", "5");
    await flows.expectStepBadge("transform", "per item, 5s apart");

    await flows.save();
    await flows.reload();
    await flows.expectStepBadge("transform", "per item, 5s apart");
    await flows.selectNode("transform");
    await flows.expectFieldValue("Seconds between items", "5");

    // Running once again takes the pause with it. The save is the proof: the
    // server refuses a pause on a step with nothing to pause between.
    await flows.fillField("Run once per item in", "");
    await flows.expectNoField("Seconds between items");
    await flows.save();
    await flows.fillField("Run once per item in", "{{ steps.loop.batches }}");
    await flows.expectFieldValue("Seconds between items", "0");
  });

  test("a run waits between its batches", async ({ page }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const run = await seedPacedRun(page.request, `Paced run ${Date.now()}`);

    // Three batches of two: two gaps, each at least the pause. Without it
    // the gaps are a few milliseconds of bookkeeping.
    const gaps = await readItemGapsMs(page.request, run, "send");
    expect(gaps).toHaveLength(2);
    for (const gap of gaps) {
      expect(gap).toBeGreaterThanOrEqual(PACED_PAUSE_SECONDS * 1000 - 10);
    }

    const flows = new FlowsPage(page);
    await flows.gotoRun(run.flowId, run.runId);
    await flows.expectRunStatus("SUCCEEDED");
    await flows.expectStepBadge("send", "per item, 1s apart");
    await flows.selectStepInRun("send");
    await flows.expectRunItemCount(3);
  });
});
