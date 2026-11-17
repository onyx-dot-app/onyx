/**
 * Page Object Model for the Security & Hardening admin page (/admin/security).
 *
 * Encapsulates the toggle rows (each rendered as an Opal <Switch> inside an
 * InputHorizontal <label>) and the save request so specs stay declarative and
 * locator churn is confined to this file.
 */

import {
  type Page,
  type Locator,
  type Response,
  expect,
} from "@playwright/test";

export const QUERY_HISTORY_LABELS = [
  "Show with User Info",
  "Anonymized",
  "Hidden",
] as const;
export type QueryHistoryLabel = (typeof QUERY_HISTORY_LABELS)[number];

export class AdminSecurityPage {
  readonly page: Page;

  // A stable, always-present, tenant-editable toggle — used as the subject for
  // round-trip persistence checks (visible in both single- and multi-tenant).
  static readonly SESSION_EXPIRY_TOGGLE =
    "Sync Session Expiry with Identity Provider";

  constructor(page: Page) {
    this.page = page;
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  /** Navigate to the page and wait for it to finish loading. */
  async goto(): Promise<void> {
    await this.page.goto("/admin/security");
    await this.waitForLoaded();
  }

  /** Reload the page and wait for it to finish loading. */
  async reload(): Promise<void> {
    await this.page.reload();
    await this.waitForLoaded();
  }

  private async waitForLoaded(): Promise<void> {
    await this.page.waitForLoadState("networkidle");
    await expect(
      this.page.getByText(AdminSecurityPage.SESSION_EXPIRY_TOGGLE)
    ).toBeVisible({ timeout: 10000 });
  }

  // ---------------------------------------------------------------------------
  // Toggle rows
  // ---------------------------------------------------------------------------

  /** The <Switch> control for the toggle row with the given title. */
  toggle(title: string): Locator {
    return this.page
      .getByText(title)
      .locator("xpath=ancestor::label[1]")
      .getByRole("switch");
  }

  /** Whether the named toggle is currently on (aria-checked === "true"). */
  async isToggleOn(title: string): Promise<boolean> {
    return (await this.toggle(title).getAttribute("aria-checked")) === "true";
  }

  /** Flip the named toggle and wait for the save request to succeed. */
  async clickToggleAndSave(title: string): Promise<void> {
    const saved = this.page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/admin/security") &&
        response.request().method() === "PUT",
      { timeout: 5000 }
    );
    await this.toggle(title).click();
    expect((await saved).ok()).toBe(true);
  }

  /** Assert the named toggle is in the expected on/off state. */
  async expectToggle(title: string, on: boolean): Promise<void> {
    await expect(this.toggle(title)).toHaveAttribute(
      "aria-checked",
      on ? "true" : "false"
    );
  }

  // ---------------------------------------------------------------------------
  // Chat retention ("Keep Chat History")
  // ---------------------------------------------------------------------------

  /** The "Keep Chat History" row on the Admin Controls card. */
  retentionField(): Locator {
    return this.page.locator("label").filter({ hasText: "Keep Chat History" });
  }

  get retentionTrigger(): Locator {
    return this.retentionField().locator('[role="combobox"]');
  }

  /** The "In days" input shown once "Custom Retention" is selected. */
  get retentionCustomInput(): Locator {
    return this.retentionField().getByPlaceholder("In days");
  }

  /** First icon button in the custom input restores the default (Forever). */
  get retentionRestoreDefaultButton(): Locator {
    return this.retentionField()
      .locator(".opal-input")
      .getByRole("button")
      .first();
  }

  /** Second icon button in the custom input reopens the preset dropdown. */
  get retentionMoreButton(): Locator {
    return this.retentionField()
      .locator(".opal-input")
      .getByRole("button")
      .nth(1);
  }

  get reduceRetentionModal(): Locator {
    return this.page.getByText("Reduce chat retention?");
  }

  retentionOption(label: string): Locator {
    return this.page.getByRole("option", { name: label, exact: true });
  }

  async openRetentionDropdown(): Promise<void> {
    await this.retentionTrigger.click();
  }

  async selectRetentionPreset(label: string): Promise<void> {
    await this.openRetentionDropdown();
    await this.retentionOption(label).click();
  }

  /** Choose "Custom Retention" and wait for the days input to appear. */
  async chooseCustomRetention(): Promise<void> {
    await this.openRetentionDropdown();
    await this.retentionOption("Custom Retention").click();
    await expect(this.retentionCustomInput).toBeVisible();
  }

  async confirmRetentionReduction(): Promise<void> {
    await expect(this.reduceRetentionModal).toBeVisible();
    const saved = this.waitForSettingsPatch();
    await this.page.getByRole("button", { name: "Reduce retention" }).click();
    expect((await saved).ok()).toBeTruthy();
  }

  async cancelRetentionReduction(): Promise<void> {
    // No inputs live inside the modal, so Escape dismisses it immediately.
    await this.page.keyboard.press("Escape");
    await expect(this.reduceRetentionModal).toHaveCount(0);
  }

  /**
   * Enter a custom retention value coming from Forever/a larger value. This
   * shortens the retention window, so it triggers (and confirms) the reduction
   * prompt.
   */
  async setCustomRetention(days: string): Promise<void> {
    await this.chooseCustomRetention();
    await this.retentionCustomInput.fill(days);
    await this.retentionCustomInput.blur();
    await this.confirmRetentionReduction();
  }

  async restoreRetentionDefault(): Promise<void> {
    const saved = this.waitForSettingsPatch();
    await this.retentionRestoreDefaultButton.click();
    expect((await saved).ok()).toBeTruthy();
  }

  /** Best-effort reset so shared state is left at the safe "Forever" default. */
  async resetRetentionToForever(): Promise<void> {
    await this.goto();
    if (await this.retentionCustomInput.isVisible().catch(() => false)) {
      const saved = this.waitForSettingsPatch();
      await this.retentionRestoreDefaultButton.click();
      await saved.catch(() => {});
      return;
    }
    // The trigger is a read-only input: its text is its value.
    if ((await this.retentionTrigger.inputValue()).includes("Forever")) {
      return;
    }
    const saved = this.waitForSettingsPatch();
    await this.selectRetentionPreset("Forever");
    expect((await saved).ok()).toBeTruthy();
  }

  // ---------------------------------------------------------------------------
  // Query History Visibility
  // ---------------------------------------------------------------------------

  /** The "Query History Visibility" row on the Admin Controls card. */
  queryHistoryField(): Locator {
    return this.page
      .locator("label")
      .filter({ hasText: "Query History Visibility" })
      .first();
  }

  get queryHistoryTrigger(): Locator {
    return this.queryHistoryField().locator('[role="combobox"]');
  }

  /** The selected option label of the Query History Visibility dropdown. */
  async getQueryHistoryValue(): Promise<string> {
    await expect(this.queryHistoryField()).toBeVisible({ timeout: 10000 });
    const text = await this.queryHistoryTrigger.inputValue();
    for (const label of QUERY_HISTORY_LABELS) {
      if (text.includes(label)) return label;
    }
    return text;
  }

  /** Open the page and select the option, unless it is already selected. */
  async setQueryHistoryType(value: QueryHistoryLabel): Promise<void> {
    await this.goto();
    if ((await this.getQueryHistoryValue()) === value) return;

    await this.queryHistoryTrigger.scrollIntoViewIfNeeded();
    await this.queryHistoryTrigger.click();
    const option = this.page
      .locator('[role="option"]')
      .filter({ hasText: value });
    await expect(option).toBeVisible({ timeout: 3000 });
    const saved = this.waitForSettingsPatch();
    await option.click();
    expect((await saved).ok()).toBeTruthy();
  }

  /** Resolves with the next workspace-settings PATCH; start it before the action. */
  private waitForSettingsPatch(): Promise<Response> {
    return this.page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/admin/settings" &&
        response.request().method() === "PATCH"
    );
  }
}
