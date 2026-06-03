/**
 * Page Object Model for the Flows surface (/flows and /flows/[id]).
 *
 * The canvas derives node positions from the spec rather than storing them,
 * so everything here is expressed against the graph the user can see — node
 * cards, edges, the zoom readout — never against the transform matrix.
 */

import { type Locator, type Page, expect } from "@playwright/test";

const LIST_PATH = "/flows";

/** Outcome ring drawn around a step in the run view. */
export type StepOutcome = "succeeded" | "failed" | "skipped";

// Anchored to class boundaries on purpose. The node card also carries
// `hover:border-border-02`, so a bare /border-border-02/ matches every card
// whatever its outcome — an assertion that can never fail.
const OUTCOME_BORDER: Record<StepOutcome, RegExp> = {
  succeeded: /(?:^|\s)border-status-success-05(?:\s|$)/,
  failed: /(?:^|\s)border-status-error-05(?:\s|$)/,
  skipped: /(?:^|\s)border-border-02(?:\s|$)/,
};
const EDITOR_PATH_REGEX = /\/flows\/[0-9a-f-]{36}$/;

/**
 * How long a resumed run may take to leave AWAITING_DECISION.
 *
 * Answering re-queues the run, so this is a worker round trip rather than a
 * render — the page's own poll interval is only part of it.
 */
const RESUME_TIMEOUT_MS = 60_000;

/** The step kinds the palette offers, by their button label. */
export type StepKind =
  | "HTTP request"
  | "AI"
  | "Code"
  | "Transform"
  | "Condition"
  | "Loop"
  | "Approval";

export class FlowsPage {
  readonly page: Page;

  readonly newFlowButton: Locator;
  readonly canvas: Locator;
  readonly nodes: Locator;
  readonly edges: Locator;
  readonly zoomLevel: Locator;
  readonly zoomInButton: Locator;
  readonly zoomOutButton: Locator;
  readonly fitButton: Locator;
  readonly inspector: Locator;
  readonly inspectorNameInput: Locator;
  readonly deleteStepButton: Locator;
  readonly saveButton: Locator;
  readonly publishButton: Locator;
  readonly activateButton: Locator;
  readonly testRunButton: Locator;
  readonly runPanel: Locator;
  readonly runItems: Locator;
  readonly decisionPanel: Locator;
  readonly approveButton: Locator;
  readonly rejectButton: Locator;

  constructor(page: Page) {
    this.page = page;

    this.newFlowButton = page.getByRole("button", { name: "New flow" });
    this.canvas = page.getByTestId("flow-canvas");
    this.nodes = page.locator("[data-flow-node]");
    this.edges = page.getByTestId("flow-edge");
    this.zoomLevel = page.getByTestId("canvas-zoom-level");
    this.zoomInButton = page.getByRole("button", { name: "Zoom in" });
    this.zoomOutButton = page.getByRole("button", { name: "Zoom out" });
    this.fitButton = page.getByRole("button", { name: "Fit to view" });
    this.inspector = page.getByTestId("node-inspector");
    this.inspectorNameInput = this.inspector.getByRole("textbox").first();
    this.deleteStepButton = page.getByRole("button", { name: "Delete step" });
    this.saveButton = page.getByRole("button", { name: "Save", exact: true });
    this.publishButton = page.getByRole("button", { name: "Publish" });
    this.activateButton = page.getByRole("button", { name: "Activate" });
    this.testRunButton = page.getByRole("button", { name: "Test run" });
    this.runPanel = page.locator("aside").last();
    this.runItems = page.getByTestId("node-run-item");
    this.decisionPanel = page.getByTestId("decision-panel");
    this.approveButton = page.getByTestId("decision-approve");
    this.rejectButton = page.getByTestId("decision-reject");
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  async gotoList(): Promise<void> {
    await this.page.goto(LIST_PATH);
    await expect(this.newFlowButton).toBeVisible();
  }

  /**
   * Create a flow and land on its editor.
   *
   * The list page creates the flow through the API and redirects, so the
   * canvas being visible is what proves the round trip worked.
   */
  async createFlow(): Promise<void> {
    await this.newFlowButton.click();
    await expect(this.page).toHaveURL(EDITOR_PATH_REGEX);
    await expect(this.canvas).toBeVisible();
    // A new flow opens on one HTTP step, so wait for the graph to settle
    // before a caller starts adding to it.
    await expect(this.nodes).toHaveCount(1);
  }

  async reload(): Promise<void> {
    await this.page.reload();
    await expect(this.canvas).toBeVisible();
  }

  // ---------------------------------------------------------------------------
  // Building the graph
  // ---------------------------------------------------------------------------

  /** Add a step, wired after whatever is selected. */
  async addStep(kind: StepKind): Promise<void> {
    const before = await this.nodes.count();
    await this.page.getByRole("button", { name: kind, exact: true }).click();
    await expect(this.nodes).toHaveCount(before + 1);
  }

  node(nodeId: string): Locator {
    return this.page.locator(`[data-flow-node="${nodeId}"]`);
  }

  async selectNode(nodeId: string): Promise<void> {
    await this.node(nodeId).click();
    await expect(this.inspector).toBeVisible();
  }

  /**
   * Click empty canvas, which clears the selection.
   *
   * Aimed at the top-left corner: the layout centres the graph, so that
   * corner is reliably background even on a wide flow.
   */
  async clickEmptyCanvas(): Promise<void> {
    await this.canvas.click({ position: { x: 12, y: 12 } });
  }

  async renameSelectedStep(name: string): Promise<void> {
    await this.inspectorNameInput.fill(name);
  }

  /**
   * One field of the inspector, by the title above it.
   *
   * Opal's `InputVertical` wraps its title and its control in one `<label>`,
   * so the title is the field's accessible name and `getByLabel` finds the
   * control under it.
   */
  field(title: string): Locator {
    return this.inspector.getByLabel(title);
  }

  async fillField(title: string, value: string): Promise<void> {
    await this.field(title).fill(value);
  }

  async expectField(title: string): Promise<void> {
    await expect(this.field(title)).toBeVisible();
  }

  /** A field the selected kind does not have. */
  async expectNoField(title: string): Promise<void> {
    await expect(this.field(title)).toHaveCount(0);
  }

  async deleteSelectedStep(): Promise<void> {
    const before = await this.nodes.count();
    await this.deleteStepButton.click();
    await expect(this.nodes).toHaveCount(before - 1);
  }

  // ---------------------------------------------------------------------------
  // Saving
  // ---------------------------------------------------------------------------

  async save(): Promise<void> {
    await this.saveButton.click();
    // The button reads "Saved" and disables once the draft matches the server.
    await expect(
      this.page.getByRole("button", { name: "Saved", exact: true })
    ).toBeVisible();
  }

  async publish(): Promise<void> {
    await this.publishButton.click();
    await expect(this.activateButton).toBeEnabled();
  }

  // ---------------------------------------------------------------------------
  // Viewport
  // ---------------------------------------------------------------------------

  /** Current zoom as a number, for control flow rather than assertions. */
  async currentZoomPercent(): Promise<number> {
    const text = (await this.zoomLevel.innerText()).trim();
    return Number.parseInt(text.replace("%", ""), 10);
  }

  // ---------------------------------------------------------------------------
  // Assertions
  // ---------------------------------------------------------------------------

  async expectStepCount(count: number): Promise<void> {
    await expect(this.nodes).toHaveCount(count);
  }

  async expectEdgeCount(count: number): Promise<void> {
    await expect(this.edges).toHaveCount(count);
  }

  /** A condition's branches are drawn and labelled. */
  async expectBranchEdge(branch: "true" | "false"): Promise<void> {
    await expect(
      this.edges.filter({ has: this.page.locator(`text=${branch}`) })
    ).toHaveCount(1);
  }

  async expectStepLabelled(nodeId: string, name: string): Promise<void> {
    await expect(this.node(nodeId)).toContainText(name);
  }

  /** A step nothing reaches is outlined rather than hidden. */
  async expectStepUnreachable(nodeId: string): Promise<void> {
    await expect(this.node(nodeId)).toHaveClass(/border-dashed/);
  }

  async expectStepConnected(nodeId: string): Promise<void> {
    await expect(this.node(nodeId)).not.toHaveClass(/border-dashed/);
  }

  async expectInspectorOpen(): Promise<void> {
    await expect(this.inspector).toBeVisible();
  }

  async expectInspectorClosed(): Promise<void> {
    await expect(this.inspector).toBeHidden();
  }

  async expectSelectedStepNamed(name: string): Promise<void> {
    await expect(this.inspectorNameInput).toHaveValue(name);
  }

  async expectZoomAbove(percent: number): Promise<void> {
    await expect
      .poll(() => this.currentZoomPercent(), {
        message: `zoom should rise above ${percent}%`,
      })
      .toBeGreaterThan(percent);
  }

  async expectZoomBelow(percent: number): Promise<void> {
    await expect
      .poll(() => this.currentZoomPercent(), {
        message: `zoom should fall below ${percent}%`,
      })
      .toBeLessThan(percent);
  }

  // ---------------------------------------------------------------------------
  // Run view
  // ---------------------------------------------------------------------------

  /**
   * Select a step on the run view.
   *
   * Separate from `selectNode`, which waits for the editor's inspector — the
   * run view shows a read-only panel instead, so waiting for the inspector
   * there would just time out.
   */
  async selectStepInRun(nodeId: string): Promise<void> {
    await this.node(nodeId).click();
  }

  async gotoRun(flowId: string, runId: string): Promise<void> {
    await this.page.goto(`${LIST_PATH}/${flowId}/runs/${runId}`);
    await expect(this.canvas).toBeVisible();
  }

  /** Start a test run from the editor; the page follows the new run. */
  async startTestRun(): Promise<void> {
    await this.testRunButton.click();
    await expect(this.page).toHaveURL(
      /\/flows\/[0-9a-f-]{36}\/runs\/[0-9a-f-]{36}$/
    );
    await expect(this.canvas).toBeVisible();
  }

  async expectRunStatus(label: string, timeout?: number): Promise<void> {
    await expect(this.page.getByTestId(`run-status-${label}`)).toBeVisible({
      timeout,
    });
  }

  // ---------------------------------------------------------------------------
  // Approvals
  // ---------------------------------------------------------------------------

  /**
   * Answer the approval the run is parked on.
   *
   * The panel disappears as soon as the run leaves AWAITING_DECISION, so
   * waiting for that is what proves the answer reached the server rather
   * than just that a button was clickable.
   */
  async decide(
    decision: "approve" | "reject",
    comment?: string
  ): Promise<void> {
    await expect(this.decisionPanel).toBeVisible();
    if (comment !== undefined) {
      await this.decisionPanel.getByRole("textbox").fill(comment);
    }
    await (
      decision === "approve" ? this.approveButton : this.rejectButton
    ).click();
    await expect(this.decisionPanel).toBeHidden({ timeout: RESUME_TIMEOUT_MS });
  }

  async expectAwaitingDecision(question: string): Promise<void> {
    await expect(this.decisionPanel).toBeVisible();
    await expect(this.decisionPanel).toContainText(question);
  }

  async expectNoDecisionPanel(): Promise<void> {
    await expect(this.decisionPanel).toBeHidden();
  }

  /** A step the run never reached has no row to show. */
  async expectStepNotRun(nodeId: string): Promise<void> {
    await this.selectStepInRun(nodeId);
    await expect(this.runItems).toHaveCount(0);
  }

  /** Each step wears the outcome it had, so the graph reads as the run. */
  async expectStepOutcome(nodeId: string, outcome: StepOutcome): Promise<void> {
    await expect(this.node(nodeId)).toHaveClass(OUTCOME_BORDER[outcome]);
  }

  /** A skipped branch reads as muted rather than alarming. */
  async expectStepDimmed(nodeId: string): Promise<void> {
    await expect(this.node(nodeId)).toHaveClass(/opacity-60/);
  }

  async expectStepNotDimmed(nodeId: string): Promise<void> {
    await expect(this.node(nodeId)).not.toHaveClass(/opacity-60/);
  }

  async expectRunItemCount(count: number): Promise<void> {
    await expect(this.runItems).toHaveCount(count);
  }

  async expectRunPanelContains(text: string): Promise<void> {
    await expect(this.runPanel).toContainText(text);
  }

  /** Something the run page says outside the step panel, such as why it failed. */
  async expectRunPageContains(text: string): Promise<void> {
    await expect(this.page.getByText(text).first()).toBeVisible();
  }
}
