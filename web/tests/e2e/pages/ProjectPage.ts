import { Locator, Page, expect } from "@playwright/test";
import { SidebarChatRow } from "@tests/e2e/pages/AppSidebarPage";

/** A chat row in the project page's "Recent Chats" list. */
export class ProjectChatRow extends SidebarChatRow {
  override get root(): Locator {
    return this.page
      .getByTestId("ProjectChatItem")
      .filter({ hasText: this.name });
  }

  override get optionsButton(): Locator {
    return this.root.getByLabel("Chat options");
  }
}

/** A project's page: its input bar and the list of its chats. */
export class ProjectPage {
  constructor(private readonly page: Page) {}

  async goto(projectId: number): Promise<void> {
    await this.page.goto(`/app?projectId=${projectId}`);
    await expect(
      this.page.getByText("Recent Chats", { exact: true })
    ).toBeVisible();
  }

  /** A chat in the project's list, looked up by its visible name. */
  chatRow(name: string): ProjectChatRow {
    return new ProjectChatRow(this.page, name);
  }
}
