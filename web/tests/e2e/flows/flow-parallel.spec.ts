import { test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { FlowsPage } from "@tests/e2e/pages/FlowsPage";
import { seedParallelRun } from "@tests/e2e/utils/flows";

/**
 * Calling an endpoint once per item, several calls at a time.
 *
 * The deployment's SSRF policy will not let a flow reach anything on this
 * machine, so a run here cannot succeed — but that is useful rather than a
 * gap. A refused call is the one outcome with no outside endpoint in it,
 * and it shows the calls ran on the worker, under the tenant's policy, and
 * that the failure names the item it came from. What happens after a
 * request leaves is covered by the node tests.
 */
test.describe("Flows parallel step", () => {
  test("a parallel step keeps its settings and fans out on its own", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    await flows.addStep("Parallel");
    await flows.selectNode("parallel");

    await flows.expectFieldValue("Calls at a time", "5");

    // The server caps the calls in flight, so the editor must not let an
    // author build a spec it will refuse.
    await flows.fillField("Calls at a time", "50");
    await flows.expectFieldValue("Calls at a time", "10");

    await flows.fillField(
      "Call once for each item in",
      "{{ steps.http.body }}"
    );
    await flows.fillField("URL", "https://api.example.com/users/{{ item }}");
    await flows.fillField("Calls at a time", "3");

    // It already runs once per item of its own list; fanning that out again
    // would multiply the calls `concurrency` exists to cap.
    await flows.expectNoField("Run once per item in");

    await flows.save();
    await flows.reload();

    await flows.selectNode("parallel");
    await flows.expectFieldValue(
      "Call once for each item in",
      "{{ steps.http.body }}"
    );
    await flows.expectFieldValue(
      "URL",
      "https://api.example.com/users/{{ item }}"
    );
    await flows.expectFieldValue("Calls at a time", "3");
  });

  test("a refused call fails the run and names the item", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const { flowId, runId } = await seedParallelRun(
      page.request,
      `Parallel run ${Date.now()}`,
      [7, 8, 9]
    );

    const flows = new FlowsPage(page);
    await flows.gotoRun(flowId, runId);
    await flows.expectRunStatus("FAILED");
    await flows.expectStepOutcome("lookup", "failed");

    // All three go out at once and all three are refused. The lowest item
    // is reported however the calls raced, so this reads the same every run.
    await flows.expectRunPageContains("item 0: blocked by SSRF policy");
  });
});
