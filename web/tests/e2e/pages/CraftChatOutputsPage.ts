import { expect, type Locator, type Page } from "@playwright/test";
import { CraftOutputsPage } from "@tests/e2e/pages/CraftOutputsPage";

export class CraftChatOutputsPage {
  readonly outputs: CraftOutputsPage;

  constructor(private readonly page: Page) {
    this.outputs = new CraftOutputsPage(page);
  }

  private turn(index: number): Locator {
    return this.page.getByTestId(`craft-turn-outputs-${index}`);
  }

  private card(id: string): Locator {
    return this.page.getByTestId(`craft-output-card-${id}`);
  }

  async expectCards(index: number, names: string[]): Promise<void> {
    await expect(
      this.turn(index).getByTestId(/^craft-output-card-/)
    ).toHaveCount(names.length);
    for (const name of names) {
      await expect(
        this.turn(index).getByRole("button", { name, exact: true })
      ).toBeVisible();
    }
  }

  async expectCardAtTurn(id: string, index: number): Promise<void> {
    await expect(this.page.getByTestId(`craft-output-card-${id}`)).toHaveCount(
      1
    );
    await expect(
      this.turn(index).getByTestId(`craft-output-card-${id}`)
    ).toBeVisible();
  }

  async expectUnread(path: string, unread: boolean): Promise<void> {
    const dot = this.outputs.panel
      .getByRole("button", { name: path, exact: true })
      .getByRole("img", { name: "New or updated" });
    if (unread) await expect(dot).toBeVisible();
    else await expect(dot).toHaveCount(0);
  }

  async openCard(id: string, name: string): Promise<void> {
    await expect(this.card(id)).toHaveAccessibleName(name);
    await this.card(id).click();
    await this.outputs.expectMode("medium");
  }

  async viewAll(index: number, count: number): Promise<void> {
    await this.turn(index)
      .getByRole("button", { name: `View all ${count} outputs`, exact: true })
      .click();
    await this.outputs.expectMode("medium");
  }

  async expectOutput(name: string, visible: boolean): Promise<void> {
    const tile = this.outputs.panel.getByRole("button", { name, exact: true });
    if (visible) await expect(tile).toBeVisible();
    else await expect(tile).toHaveCount(0);
  }

  async expectActiveTab(name: string): Promise<void> {
    await expect(
      this.page.getByRole("tab", { name, exact: true })
    ).toHaveAttribute("aria-selected", "true");
  }

  async selectTab(name: string): Promise<void> {
    await this.page.getByRole("tab", { name, exact: true }).click();
    await this.expectActiveTab(name);
  }

  async showAllTurns(): Promise<void> {
    await this.outputs.panel
      .getByRole("button", { name: /^Remove Turn .+ outputs$/ })
      .click();
  }
}
