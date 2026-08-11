import { expect, type Locator, type Page } from "@playwright/test";

/** Items in an agent row's overflow menu, keyed by the affordance that renders them. */
export type AgentRowAction =
  | "List Agent"
  | "Unlist Agent"
  | "Share"
  | "Stats"
  | "Delete";

export class AdminAgentsPage {
  readonly page: Page;
  readonly newAgentLink: Locator;

  constructor(page: Page) {
    this.page = page;
    this.newAgentLink = page.getByRole("link", { name: "New Agent" });
  }

  async goto(): Promise<void> {
    await this.page.goto("/admin/agents");
    await this.page.waitForLoadState("networkidle");
  }

  rowActions(agentId: number): Locator {
    return this.page.getByTestId(`agent-row-actions-${agentId}`);
  }

  /** Outside the overflow menu, and only for an editable agent. */
  editButton(agentId: number): Locator {
    return this.rowActions(agentId).getByRole("button", { name: "Edit Agent" });
  }

  overflowTrigger(agentId: number): Locator {
    return this.rowActions(agentId).getByRole("button", {
      name: "Agent actions",
    });
  }

  /** Absent when the row has no actions the caller may take. */
  async expectOverflowHidden(agentId: number): Promise<void> {
    await expect(this.rowActions(agentId)).toBeVisible({ timeout: 10_000 });
    await expect(this.overflowTrigger(agentId)).toHaveCount(0);
  }

  async openOverflow(agentId: number): Promise<void> {
    const trigger = this.overflowTrigger(agentId);
    await expect(trigger).toBeVisible({ timeout: 10_000 });
    await trigger.click();
  }

  async expectActions(
    agentId: number,
    expected: { visible: AgentRowAction[]; hidden: AgentRowAction[] }
  ): Promise<void> {
    await this.openOverflow(agentId);
    for (const action of expected.visible) {
      await expect(this.page.getByText(action, { exact: true })).toBeVisible({
        timeout: 10_000,
      });
    }
    for (const action of expected.hidden) {
      await expect(this.page.getByText(action, { exact: true })).toHaveCount(0);
    }
    // Close so the next row's menu isn't shadowed.
    await this.page.keyboard.press("Escape");
  }
}
