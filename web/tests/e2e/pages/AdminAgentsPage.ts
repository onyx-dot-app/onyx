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
    return this.page.getByTestId(`edit-agent-${agentId}`);
  }

  overflowTrigger(agentId: number): Locator {
    return this.rowActions(agentId).getByRole("button", {
      name: "Agent actions",
    });
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
    // a closing menu's items are still role=dialog descendants; settle first
    await expect(this.page.getByRole("dialog")).toHaveCount(0);
    await this.openOverflow(agentId);

    // LineItem nests <p> in <p>, so getByText matches twice per entry
    const menu = this.page.getByRole("dialog").last();
    for (const action of expected.visible) {
      await expect(menu.getByRole("button", { name: action })).toBeVisible({
        timeout: 10_000,
      });
    }
    for (const action of expected.hidden) {
      await expect(menu.getByRole("button", { name: action })).toHaveCount(0);
    }
    // Close so the next row's menu isn't shadowed.
    await this.page.keyboard.press("Escape");
    await expect(this.page.getByRole("dialog")).toHaveCount(0);
  }
}
