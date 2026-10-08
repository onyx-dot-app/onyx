import { test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { FlowsPage } from "@tests/e2e/pages/FlowsPage";

/**
 * The canvas is the part of Flows that unit tests cannot reach: layout runs
 * against real measured elements, and pan, zoom and selection are pointer
 * behaviour. These specs cover the graph a user can build and see.
 *
 * Node ids are assigned by the editor from the step kind — the first HTTP
 * step is `http`, the first condition `condition` — so the specs can address
 * steps without reading them back out of the spec first.
 */
test.describe("Flows canvas", () => {
  test("builds a branching graph and persists it", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();

    // A new flow opens on a single step, which is the graph's entry point.
    await flows.expectStepCount(1);
    await flows.expectEdgeCount(0);
    await flows.expectStepConnected("http");

    // Adding a step wires it after whatever is selected.
    await flows.selectNode("http");
    await flows.addStep("Condition");
    await flows.expectEdgeCount(1);

    // A step added after a condition joins its true branch, so the edge is
    // drawn and labelled rather than left ambiguous.
    await flows.selectNode("condition");
    await flows.addStep("Transform");
    await flows.expectStepCount(3);
    await flows.expectEdgeCount(2);
    await flows.expectBranchEdge("true");

    // Renaming redraws the node immediately — there is no apply step.
    await flows.selectNode("transform");
    await flows.renameSelectedStep("Summarise the result");
    await flows.expectStepLabelled("transform", "Summarise the result");

    // The rename survives a save and a reload, which is what proves the
    // editor's draft actually reached the server.
    await flows.save();
    await flows.reload();
    await flows.expectStepCount(3);
    await flows.expectStepLabelled("transform", "Summarise the result");
  });

  test("shows a step nothing reaches as unconnected", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();

    // With nothing selected there is no step to wire behind, so the new step
    // lands unconnected. The canvas outlines it rather than hiding it.
    await flows.clickEmptyCanvas();
    await flows.addStep("Transform");
    await flows.expectStepUnreachable("transform");
    await flows.expectStepConnected("http");
    await flows.expectEdgeCount(0);
  });

  test("selects a step and clears the selection on the background", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();

    await flows.selectNode("http");
    await flows.expectInspectorOpen();
    await flows.expectSelectedStepNamed("http");

    // The same pointer handler that starts a pan also drops the selection,
    // so clicking the background has to close the inspector.
    await flows.clickEmptyCanvas();
    await flows.expectInspectorClosed();
  });

  test("zooms in and back out", async ({ page }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();

    const fitted = await flows.currentZoomPercent();

    await flows.zoomInButton.click();
    await flows.expectZoomAbove(fitted);

    await flows.zoomOutButton.click();
    await flows.zoomOutButton.click();
    await flows.expectZoomBelow(fitted);

    // Fit returns the graph to the framing it opened with.
    await flows.fitButton.click();
    await flows.expectZoomAbove(fitted - 1);
  });

  test("deletes a step and heals the graph around it", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();

    // Build http -> transform -> ai, then remove the middle step. The two
    // ends should join rather than the flow being severed.
    await flows.selectNode("http");
    await flows.addStep("Transform");
    await flows.selectNode("transform");
    await flows.addStep("AI");
    await flows.expectEdgeCount(2);

    await flows.selectNode("transform");
    await flows.deleteSelectedStep();

    await flows.expectStepCount(2);
    await flows.expectEdgeCount(1);
    await flows.expectStepConnected("ai");
  });
});
