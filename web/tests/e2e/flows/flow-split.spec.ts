import { test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { FlowsPage } from "@tests/e2e/pages/FlowsPage";

/**
 * Turning one piece of text into a list.
 *
 * The tidying options are the part worth pinning: a list typed by a person
 * has spaces in it and a trailing comma, so the defaults do the obvious
 * thing — and somebody who needs the raw pieces has to be able to say so.
 */
test.describe("Flows split step", () => {
  test("a split opens on the defaults a hand-typed list needs", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    await flows.addStep("Split");
    await flows.selectNode("split");

    await flows.expectFieldValue("Split on", ",");
    await flows.expectOptionChecked("Trim spaces around each piece", true);
    await flows.expectOptionChecked("Drop empty pieces", true);

    // Splitting a list per item is ordinary, so this one may fan out —
    // unlike the branching and waiting kinds.
    await flows.expectField("Run once per item in");
  });

  test("the tidying can be turned off, and it sticks", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    await flows.addStep("Split");
    await flows.selectNode("split");

    await flows.fillField("Text to split", "{{ trigger.tags }}");
    await flows.fillField("Split on", "\\n");
    await flows.toggleInspectorOption("Trim spaces around each piece");
    await flows.expectOptionChecked("Trim spaces around each piece", false);

    // Saving is the real check: the server parses the spec and rejects
    // anything it cannot execute, an empty separator included.
    await flows.save();
    await flows.reload();

    await flows.selectNode("split");
    await flows.expectFieldValue("Split on", "\\n");
    await flows.expectOptionChecked("Trim spaces around each piece", false);
    await flows.expectOptionChecked("Drop empty pieces", true);
  });
});
