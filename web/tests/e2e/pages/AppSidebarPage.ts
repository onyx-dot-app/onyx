import { Locator, Page, expect } from "@playwright/test";

/**
 * The Projects popover that the app sidebar shows in place of the projects tree
 * while it is folded.
 */
export class ProjectsPopover {
  constructor(readonly page: Page) {}

  get trigger(): Locator {
    return this.page.getByTestId("AppSidebar/projects");
  }

  get content(): Locator {
    return this.page.getByTestId("ProjectsPopover");
  }

  get searchField(): Locator {
    return this.content.getByTestId("ProjectsPopover/search");
  }

  get newProjectButton(): Locator {
    return this.content.getByTestId("ProjectsPopover/new-project");
  }

  async open(): Promise<void> {
    await this.trigger.click();
    await expect(this.content).toBeVisible();
  }

  async search(term: string): Promise<void> {
    await this.searchField.fill(term);
  }

  async clearSearch(): Promise<void> {
    await this.searchField.fill("");
  }

  /** The row holding a project's folder tab and, when open, its chats. */
  projectRow(projectName: string): Locator {
    return this.content
      .getByTestId("ProjectsPopover/row")
      .filter({ hasText: projectName });
  }

  get projectRows(): Locator {
    return this.content.getByTestId("ProjectsPopover/row");
  }

  chatRow(projectName: string, chatName: string): Locator {
    return this.projectRow(projectName).getByText(chatName, { exact: true });
  }

  /**
   * The chat's click target. A chat row is a `LineItemButton` with an `href`,
   * which renders as an anchor, so target that rather than the label text.
   */
  chatLink(projectName: string, chatId: string): Locator {
    return this.projectRow(projectName).locator(`a[href*="chatId=${chatId}"]`);
  }

  /** Toggles a project's chats without navigating anywhere. */
  async toggleProjectChats(projectName: string): Promise<void> {
    await this.projectRow(projectName).getByTestId("ProjectFolderIcon").click();
  }

  async expectVisible(): Promise<void> {
    await expect(this.content).toBeVisible();
  }

  async expectHidden(): Promise<void> {
    await expect(this.content).toBeHidden();
  }

  /** The folded tab stays marked while its popover is open. */
  /** Opens a chat from the popover and waits for the app to land on it. */
  async openChat(projectName: string, chatId: string): Promise<void> {
    await this.chatLink(projectName, chatId).click();
    await expect(this.page).toHaveURL(new RegExp(`chatId=${chatId}`));
  }

  async expectTriggerSelected(): Promise<void> {
    await expect(
      this.trigger.locator("[data-interactive-state]").first()
    ).toHaveAttribute("data-interactive-state", "selected");
  }
}

/** The main application sidebar. */
export class AppSidebarPage {
  readonly projectsPopover: ProjectsPopover;

  constructor(private readonly page: Page) {
    this.projectsPopover = new ProjectsPopover(page);
  }

  async goto(): Promise<void> {
    await this.page.goto("/app");
    await this.page.waitForLoadState("networkidle");
  }

  get newProjectTab(): Locator {
    return this.page.getByRole("button", { name: "New Project" });
  }

  /** Folds the sidebar if it is not folded already. */
  async fold(): Promise<void> {
    if (await this.projectsPopover.trigger.isVisible()) return;
    await this.page.getByLabel("Close Sidebar").click();
    await expect(this.projectsPopover.trigger).toBeVisible();
  }

  async unfold(): Promise<void> {
    await this.page.getByLabel("Open Sidebar").first().click();
    await expect(this.projectsPopover.trigger).toBeHidden();
  }
}
