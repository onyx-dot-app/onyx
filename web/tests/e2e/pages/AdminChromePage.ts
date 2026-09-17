/**
 * Page Object Model for the admin chrome (`AdminChrome`) — the sidebar column
 * and the main content column that wrap every `/admin/*` page.
 *
 * Covers the mobile layout, where the sidebar is an off-screen overlay and the
 * main column carries the control that brings it back.
 */

import { expect, type Locator, type Page } from "@playwright/test";

export class AdminChromePage {
  readonly page: Page;

  // The sidebar column has no role or accessible name of its own; `data-folded`
  // is the only signal for whether it sits on- or off-screen.
  private readonly sidebar: Locator;
  private readonly openSidebarButton: Locator;
  private readonly closeSidebarButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.sidebar = page.locator(".opal-sidebar-root__overlay");
    // Scoped to the main column, so it never matches the sidebar's own control.
    this.openSidebarButton = page
      .locator("[data-main-container]")
      .getByLabel("Open Sidebar");
    this.closeSidebarButton = this.sidebar.getByLabel("Close Sidebar");
  }

  async goto(path: string): Promise<void> {
    await this.page.goto(path);
    await this.page.waitForLoadState("networkidle");
  }

  async openSidebar(): Promise<void> {
    await this.openSidebarButton.click();
  }

  async closeSidebar(): Promise<void> {
    await this.closeSidebarButton.click();
  }

  async expectOpenSidebarButtonVisible(): Promise<void> {
    await expect(this.openSidebarButton).toBeVisible();
  }

  async expectSidebarFolded(): Promise<void> {
    await expect(this.sidebar).toHaveAttribute("data-folded", "true");
  }

  async expectSidebarUnfolded(): Promise<void> {
    await expect(this.sidebar).toHaveAttribute("data-folded", "false");
  }
}
