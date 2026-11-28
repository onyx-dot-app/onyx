import { Download, Locator, Page, expect } from "@playwright/test";

/**
 * A chat session row in the sidebar (Recents or an unfolded project). Rows
 * elsewhere that open the same options menu override `root` and
 * `optionsButton`.
 */
export class SidebarChatRow {
  constructor(
    readonly page: Page,
    readonly name: string
  ) {}

  /**
   * The row container. Matched by the visible label, so it matches nothing
   * while the row shows the inline rename editor.
   */
  get root(): Locator {
    return this.page.getByTestId("ChatButton").filter({ hasText: this.name });
  }

  /** The "..." button that opens the row's options popover. */
  get optionsButton(): Locator {
    return this.root.getByTestId("ChatButton/options");
  }

  /** The options menu. Only one row's menu is open at a time. */
  get optionsPopover(): Locator {
    return this.page.getByRole("menu", { name: "Chat options" });
  }

  /**
   * The inline rename editor. The editor replaces the row's label, so this
   * cannot be scoped to the row by name; only one row renames at a time.
   */
  get renameInput(): Locator {
    return this.page.getByTestId("ChatButton").getByRole("textbox");
  }

  /** Reveals the row's actions and opens the options popover. */
  async openOptions(): Promise<void> {
    await this.root.hover();
    await this.optionsButton.click();
    await expect(this.optionsPopover).toBeVisible();
  }

  /** Opens the options popover and clicks "Rename". */
  async startRename(): Promise<void> {
    await this.openOptions();
    await this.optionsPopover.getByRole("menuitem", { name: "Rename" }).click();
  }

  /** Opens "Export As…" in the options popover and returns the download. */
  async exportAs(format: "Markdown" | "Plain Text"): Promise<Download> {
    await this.openOptions();
    await this.optionsPopover
      .getByRole("menuitem", { name: "Export As…" })
      .click();
    const download = this.page.waitForEvent("download");
    await this.optionsPopover
      .getByRole("menuitem", { name: format, exact: true })
      .click();
    return download;
  }

  /** Deletes the chat through the options popover and its confirmation. */
  async delete(): Promise<void> {
    await this.openOptions();
    await this.optionsPopover
      .getByRole("menuitem", { name: "Delete", exact: true })
      .click();
    const confirmation = this.page.getByRole("dialog", { name: "Delete Chat" });
    await confirmation.getByRole("button", { name: "Delete" }).click();
    await expect(confirmation).toBeHidden();
  }

  /** Types a new name into the rename editor and submits it. */
  async submitRename(newName: string): Promise<void> {
    await this.renameInput.fill(newName);
    await this.renameInput.press("Enter");
  }
}

/** The main application sidebar. */
export class AppSidebarPage {
  constructor(private readonly page: Page) {}

  /** A chat session row, looked up by its visible name. */
  chatRow(name: string): SidebarChatRow {
    return new SidebarChatRow(this.page, name);
  }

  async goto(): Promise<void> {
    await this.page.goto("/app");
    await this.page.waitForLoadState("networkidle");
  }

  /** The account menu tab. It renders once the signed-in user loads. */
  get accountMenu(): Locator {
    return this.page.locator("#onyx-user-dropdown");
  }

  /** The profile photo in the account menu tab. */
  get accountAvatarPhoto(): Locator {
    return this.page.locator("#onyx-user-dropdown img[src*='/profile-image']");
  }

  get newProjectTab(): Locator {
    return this.page.getByRole("button", { name: "New Project" });
  }

  /** Opens a new session in the running app, without a page load. */
  async newSession(): Promise<void> {
    await this.page.getByTestId("AppSidebar/new-session").click();
  }
}
