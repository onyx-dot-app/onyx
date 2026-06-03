import { expect, test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { FlowsPage } from "@tests/e2e/pages/FlowsPage";

/**
 * Bringing branches back together, and waiting for a moment rather than a
 * duration.
 *
 * The merge picker is the interesting half: the server only accepts a source
 * that leads to the merge, so the editor has to offer exactly those. Getting
 * that wrong is not a cosmetic bug — it is an editor that builds specs the
 * server refuses.
 */
test.describe("Flows merge and schedule steps", () => {
  test("a merge offers the steps that lead to it, and no others", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();

    // One chain, and a second step hanging off the start in parallel.
    await flows.selectNode("http");
    await flows.addStep("Transform");
    await flows.selectNode("http");
    await flows.addStep("Transform");
    await flows.expectStepCount(3);

    // The merge goes below the first branch only.
    await flows.selectNode("transform");
    await flows.addStep("Merge");
    await flows.selectNode("merge");

    const offered = await flows.readMergeCandidates();
    expect(offered).toEqual(["http", "transform"]);
    // `transform_2` is a sibling, not an ancestor: the server would reject it.
    expect(offered).not.toContain("transform_2");

    // A merge has one output per source already, and the server refuses
    // `for_each` on it — so the field is not offered rather than offered and
    // then refused on save. The loop below has it, which is what keeps this
    // from passing on a locator that never matches.
    await flows.expectNoField("Run once per item in");
    await flows.selectNode("transform");
    await flows.addStep("Loop");
    await flows.selectNode("loop");
    await flows.expectField("Run once per item in");
  });

  test("a merge with two sources round-trips through the server", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    await flows.addStep("Transform");
    await flows.selectNode("transform");
    await flows.addStep("Merge");
    await flows.selectNode("merge");

    // One source is not enough, and the editor says so before the save does.
    await flows.chooseMergeSource("http");
    await flows.expectInspectorContains("at least two");

    await flows.chooseMergeSource("transform");
    await flows.expectInspectorNotContains("at least two");

    // Saving is the real check: the server parses the spec and rejects a
    // merge whose sources do not lead to it.
    await flows.save();
    await flows.reload();
    await flows.expectStepCount(3);

    await flows.selectNode("merge");
    expect(await flows.readMergeCandidates()).toEqual(["http", "transform"]);
  });

  test("a schedule step takes a cron expression and saves", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    await flows.addStep("Schedule");
    await flows.selectNode("schedule");

    await flows.expectFieldValue("Cron expression", "0 9 * * 1-5");
    await flows.fillField("Cron expression", "30 6 * * 1");

    await flows.save();
    await flows.reload();
    await flows.selectNode("schedule");
    await flows.expectFieldValue("Cron expression", "30 6 * * 1");
  });
});
