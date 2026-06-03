import { test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { FlowsPage } from "@tests/e2e/pages/FlowsPage";
import { PARKED_QUESTION, seedParkedRun } from "@tests/e2e/utils/flows";

/**
 * An approval step stops a run until somebody answers it.
 *
 * The whole point is that nothing is held in between: the run is parked in
 * the database, and answering starts it again from the top. These specs go
 * through the real worker for exactly that reason — a mocked decision would
 * prove the button works and nothing else.
 *
 * They need a worker consuming the `scheduled_tasks` queue. Without one
 * `seedParkedRun` fails saying so, rather than the specs failing somewhere
 * confusing further down.
 */
test.describe("Flows approvals", () => {
  test("a parked run asks its question with the run's own values", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const seeded = await seedParkedRun(
      page.request,
      `E2E approval ${Date.now()}`
    );

    const flows = new FlowsPage(page);
    await flows.gotoRun(seeded.flowId, seeded.runId);

    await flows.expectRunStatus("AWAITING_DECISION");
    // The counts come from the loop that ran just before the gate, so seeing
    // them here proves the question was rendered against this run.
    await flows.expectAwaitingDecision(PARKED_QUESTION);

    // Everything before the gate finished; nothing after it has started.
    await flows.expectStepOutcome("seed", "succeeded");
    await flows.expectStepOutcome("chunk", "succeeded");
    await flows.expectStepNotRun("send");
  });

  test("approving lets the run finish", async ({ page }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const seeded = await seedParkedRun(
      page.request,
      `E2E approve ${Date.now()}`
    );

    const flows = new FlowsPage(page);
    await flows.gotoRun(seeded.flowId, seeded.runId);
    await flows.decide("approve", "numbers look right");

    await flows.expectRunStatus("SUCCEEDED", 60_000);
    await flows.expectStepOutcome("gate", "succeeded");
    await flows.expectStepOutcome("send", "succeeded");

    // The batches are back: the resumed run picked the loop's output off its
    // row rather than running it again.
    await flows.selectStepInRun("send");
    await flows.expectRunItemCount(2);
  });

  test("rejecting a gate with nowhere to go stops the run", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const seeded = await seedParkedRun(
      page.request,
      `E2E reject ${Date.now()}`
    );

    const flows = new FlowsPage(page);
    await flows.gotoRun(seeded.flowId, seeded.runId);
    await flows.decide("reject", "wrong batch size");

    // A rejected run reads as failed, not as a clean success, and says why.
    await flows.expectRunStatus("FAILED", 60_000);
    await flows.expectRunPageContains("wrong batch size");
    await flows.expectStepNotRun("send");
  });

  test("the editor offers the new step kinds and configures them", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();

    await flows.selectNode("http");
    await flows.addStep("Loop");
    await flows.selectNode("loop");
    await flows.fillField("Split this list", "{{ steps.http.body.rows }}");
    await flows.expectField("Run once per item in");

    await flows.addStep("Approval");
    await flows.selectNode("human");
    await flows.fillField("Question", "Send these?");

    // An approval cannot fan out — the server rejects it — so the field is
    // not offered rather than offered and refused on save. The loop above
    // has it, which is what keeps this from passing on a bad locator.
    await flows.expectNoField("Run once per item in");

    await flows.selectNode("loop");
    await flows.addStep("Code");
    await flows.expectStepCount(4);

    // Saving is the real check: the server validates the spec, so a green
    // save means these three kinds round-trip through its own models.
    await flows.save();
    await flows.reload();
    await flows.expectStepCount(4);
    await flows.expectStepLabelled("human", "human");
  });
});
