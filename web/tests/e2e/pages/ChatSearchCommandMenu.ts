import { expect, type Locator, type Page } from "@playwright/test";

export class ChatSearchCommandMenu {
  readonly dialog: Locator;
  private readonly input: Locator;

  constructor(private readonly page: Page) {
    this.dialog = page.locator('[role="dialog"]:has([data-command-menu-list])');
    this.input = this.dialog.getByPlaceholder(
      "Search chat sessions, projects..."
    );
  }

  async open(): Promise<void> {
    await this.page.getByRole("button", { name: "Search Chats" }).click();
    await expect(this.input).toBeVisible();
  }

  async searchChats(query: string): Promise<void> {
    const searchResponse = this.page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/chat/search" &&
        url.searchParams.get("query") === query &&
        url.searchParams.get("page") === "1" &&
        response.request().method() === "GET"
      );
    });
    await this.input.fill(query);
    const response = await searchResponse;
    expect(
      response.ok(),
      `Chat search failed with HTTP ${response.status()}`
    ).toBe(true);
  }
}
