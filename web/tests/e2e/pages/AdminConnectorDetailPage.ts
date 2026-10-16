/**
 * Page Object Model for the connector detail page (/admin/connector/{ccPairId}).
 * The status card renders once the cc-pair and its latest attempt load, so
 * `expectLoaded` tells a loaded page from one stuck on a refused fetch.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class AdminConnectorDetailPage {
  readonly page: Page;

  /** Rendered only once the cc-pair has resolved. */
  readonly indexingSection: Locator;
  /** The run list at the bottom of the page. */
  readonly runsSection: Locator;
  /** The run-type filter, shown only when the pair runs more than indexing. */
  readonly runKindFilter: Locator;
  /** The logs action of every run that has logs, newest first. */
  readonly runLogsButtons: Locator;
  /** The run list's empty state, shown once the feed has loaded with no runs. */
  readonly noRunsMessage: Locator;
  /** The failures and errors panel beside the page's own column. */
  readonly activityPanel: Locator;
  /** Opens the action menu. Present only when the caller may operate. */
  readonly manageButton: Locator;
  readonly deleteMenuItem: Locator;
  /** Enters the inline file editor of a file connector, inside Index Configurations. */
  readonly filesEditButton: Locator;
  /** Opens the connector in the creation form in edit mode. */
  readonly editConnectorButton: Locator;
  /** Unfolds the section listing the connector's settings. */
  readonly indexConfigurationsToggle: Locator;

  constructor(page: Page) {
    this.page = page;
    this.indexingSection = page.getByTestId("connector-indexing-status");
    this.runsSection = page.getByTestId("connector-runs");
    this.runKindFilter = page.getByRole("button", { name: "All Types" });
    this.runLogsButtons = page.getByRole("button", { name: "View Logs" });
    this.noRunsMessage = page.getByText("No recent indexing runs", {
      exact: true,
    });
    this.activityPanel = page.getByTestId("connector-activity");
    // without exact, a "managed-*" connector's title button also matches
    this.manageButton = page.getByRole("button", {
      name: "Manage Index",
      exact: true,
    });
    this.deleteMenuItem = page.getByRole("menuitem", { name: /Delete/i });
    // By id: the header's title pencil is also a button named "Edit".
    this.filesEditButton = page.getByTestId("file-manager-edit");
    // The header button comes first; an open Index Configurations section
    // shows a second "Edit Configs" button.
    this.editConnectorButton = page
      .getByRole("button", { name: "Edit Configs", exact: true })
      .first();
    this.indexConfigurationsToggle = page.getByRole("button", {
      name: "Expand Index Configurations",
    });
  }

  /** Unfolds Index Configurations, which starts folded and holds the settings and the file editor. */
  async expandIndexConfigurations(): Promise<void> {
    await this.indexConfigurationsToggle.click();
  }

  /** Unfolds Index Configurations and checks that a setting shows `value`. */
  async expectIndexConfigurationValue(value: string): Promise<void> {
    await this.expandIndexConfigurations();
    await expect(this.page.getByText(value).first()).toBeVisible();
  }

  async openFilesEditor(): Promise<void> {
    await this.expandIndexConfigurations();
    await this.filesEditButton.click();
  }

  async goto(ccPairId: number): Promise<void> {
    await this.page.goto(`/admin/connector/${ccPairId}`);
  }

  async expectLoaded(): Promise<void> {
    await expect(this.indexingSection).toBeVisible({ timeout: 30000 });
  }

  async expectRunsVisible(): Promise<void> {
    await expect(this.runsSection).toBeVisible({ timeout: 30000 });
  }

  /** Waits for the feed to load and show no runs. */
  async expectNoRuns(): Promise<void> {
    await expect(this.noRunsMessage).toBeVisible({ timeout: 30000 });
  }

  /** The activity panel has loaded and shows `text`, such as a failed run's error. */
  async expectActivityShows(text: string): Promise<void> {
    await expect(this.activityPanel).toContainText(text, { timeout: 30000 });
  }

  /** The activity panel shows exactly these group headings, such as "2 Failures". */
  async expectActivityGroups(headings: string[]): Promise<void> {
    await expect(
      this.activityPanel.getByText(/^\d+ (Failures?|Errors?|Resolved)$/)
    ).toHaveText(headings);
  }

  /** The activity panel has loaded with nothing to show. */
  async expectNoActivity(): Promise<void> {
    await expect(this.activityPanel).toContainText("No recent activity", {
      timeout: 30000,
    });
  }

  /** Opens the `index`-th logs button, newest first, and returns its trace dialog. */
  async openRunLogs(index: number, title: string): Promise<Locator> {
    await this.runLogsButtons.nth(index).click();
    const dialog = this.page.getByRole("dialog", { name: title });
    await expect(dialog).toBeVisible();
    return dialog;
  }

  /** Closes an open logs dialog. */
  async closeRunLogs(dialog: Locator): Promise<void> {
    await this.page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
  }

  async openManageMenu(): Promise<void> {
    await expect(this.manageButton).toBeVisible({ timeout: 30000 });
    await this.manageButton.click();
  }

  async openEditForm(): Promise<void> {
    await expect(this.editConnectorButton).toBeVisible({ timeout: 30000 });
    await this.editConnectorButton.click();
  }

  /** The connector name in the page header. */
  async expectName(name: string): Promise<void> {
    await expect(
      this.page.getByText(name, { exact: true }).first()
    ).toBeVisible({ timeout: 30000 });
  }

  async expectDeleteOffered(offered: boolean): Promise<void> {
    if (offered) {
      await expect(this.deleteMenuItem).toBeVisible();
    } else {
      await expect(this.deleteMenuItem).toHaveCount(0);
    }
  }

  /** The error page the detail page renders when the cc-pair fetch is refused. */
  async expectNotAccessible(): Promise<void> {
    await expect(
      this.page.getByText(/Failed to fetch info on Connector with ID/i)
    ).toBeVisible({ timeout: 30000 });
  }
}
