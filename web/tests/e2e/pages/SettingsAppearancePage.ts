/**
 * Page Object Model for the Appearance settings tab
 * (/app/settings/appearance).
 *
 * Covers the theme buttons, the language picker, the Transcript Width
 * select and the Chat Auto-scroll switch. The language picker lists languages by endonym (English,
 * Español, ...), so its trigger and option locators work in any UI language.
 */

import { type Page, type Locator, expect } from "@playwright/test";

type ThemeName = "System" | "Light" | "Dark";
type TranscriptWidth = "Standard" | "Wide";

export class SettingsAppearancePage {
  readonly page: Page;
  readonly themeOptions: Locator;
  readonly transcriptWidthSelect: Locator;
  readonly autoScrollSwitch: Locator;

  constructor(page: Page) {
    this.page = page;
    this.themeOptions = page.getByTestId("theme-preference");
    this.transcriptWidthSelect = page.getByRole("combobox", {
      name: "Transcript Width",
    });
    this.autoScrollSwitch = page
      .locator("label")
      .filter({ hasText: "Chat Auto-scroll" })
      .locator('button[role="switch"]');
  }

  /** Navigate to the tab and wait for it to render. */
  async goto(): Promise<void> {
    await this.page.goto("/app/settings/appearance");
    await expect(this.themeOptions).toBeVisible();
  }

  /** Open Settings from the user menu, without a page load, and switch to this tab. */
  async openFromUserMenu(): Promise<void> {
    await this.page.locator("#onyx-user-dropdown").click();
    await this.page.getByRole("menuitem", { name: "Settings" }).click();
    await this.page
      .locator('a[href="/app/settings/appearance"]')
      .click({ force: true });
    await expect(this.themeOptions).toBeVisible();
  }

  /** Reload the tab and wait for it to render. */
  async reload(): Promise<void> {
    await this.page.reload();
    await expect(this.themeOptions).toBeVisible();
  }

  themeButton(name: ThemeName): Locator {
    return this.themeOptions.getByRole("button", { name, exact: true });
  }

  async chooseTheme(name: ThemeName): Promise<void> {
    const saved = this.page.waitForResponse((response) =>
      response.url().includes("/api/user/theme-preference")
    );
    await this.themeButton(name).click();
    expect((await saved).ok()).toBe(true);
    await expect(this.themeButton(name)).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  }

  /** Assert whether the page renders in dark mode. */
  async expectDarkMode(enabled: boolean): Promise<void> {
    const html = this.page.locator("html");
    if (enabled) {
      await expect(html).toHaveClass(/\bdark\b/);
    } else {
      await expect(html).not.toHaveClass(/\bdark\b/);
    }
  }

  async setTranscriptWidth(width: TranscriptWidth): Promise<void> {
    await this.transcriptWidthSelect.click();
    await this.page.getByRole("option", { name: width, exact: true }).click();
    await expect(this.transcriptWidthSelect).toHaveValue(width);
  }

  async setAutoScroll(enabled: boolean): Promise<void> {
    await this.autoScrollSwitch.waitFor({ state: "visible" });
    const isChecked =
      (await this.autoScrollSwitch.getAttribute("aria-checked")) === "true";
    if (isChecked !== enabled) {
      await this.autoScrollSwitch.click();
    }
    await expect(this.autoScrollSwitch).toHaveAttribute(
      "aria-checked",
      String(enabled)
    );
  }

  /** The language select trigger, located by the endonym it displays. */
  languageSelect(currentEndonym: string): Locator {
    return this.page
      .getByRole("combobox")
      .and(this.page.locator(`[value="${currentEndonym}"]`));
  }

  /** Open the language select and choose a language by its endonym. */
  async switchLanguage(
    currentEndonym: string,
    targetEndonym: string
  ): Promise<void> {
    const select = this.languageSelect(currentEndonym);
    await expect(select).toBeVisible();
    await select.click();
    await this.page
      .getByRole("option", { name: targetEndonym, exact: true })
      .click();
  }

  /** Assert the document language and a marker string for the active locale. */
  async expectLocale(lang: string, markerText: string): Promise<void> {
    await expect(this.page.locator("html")).toHaveAttribute("lang", lang);
    await expect(this.page.getByText(markerText).first()).toBeVisible();
  }
}
