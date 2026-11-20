/**
 * Page Object Model for the Appearance settings tab
 * (/app/settings/appearance).
 *
 * Covers the theme buttons, the language picker, the font selects, the
 * Transcript Width select and the Chat Auto-scroll switch. The language
 * picker lists languages by endonym (English,
 * Español, ...), so its trigger and option locators work in any UI language.
 */

import { type Page, type Locator, expect } from "@playwright/test";
import type { InterfaceFont } from "@/lib/appearance/preferences";

type ThemeName = "System" | "Light" | "Dark";
type TranscriptWidth = "Standard" | "Wide";

export class SettingsAppearancePage {
  readonly page: Page;
  readonly themeOptions: Locator;
  readonly transcriptWidthSelect: Locator;
  readonly autoScrollSwitch: Locator;
  readonly interfaceFontSelect: Locator;
  readonly responseFontSelect: Locator;
  readonly interfaceFontTitle: Locator;

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
    this.interfaceFontSelect = page.getByRole("combobox", {
      name: "Interface Font",
    });
    this.responseFontSelect = page.getByRole("combobox", {
      name: "Response Font",
    });
    this.interfaceFontTitle = page.getByText("Interface Font", {
      exact: true,
    });
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

  /** Choose a font in one of the font selects by its label and wait for the save. */
  async chooseFont(select: Locator, label: string): Promise<void> {
    const saved = this.page.waitForResponse((response) =>
      response.url().includes("/api/user/appearance")
    );
    await select.click();
    await this.page.getByRole("option", { name: label, exact: true }).click();
    expect((await saved).ok()).toBe(true);
    await expect(select).toHaveValue(label);
  }

  /** Assert the interface font attribute and the font the body renders in. */
  async expectInterfaceFont(
    font: InterfaceFont,
    renderedFamily: RegExp
  ): Promise<void> {
    await expect(this.page.locator("html")).toHaveAttribute(
      "data-interface-font",
      font
    );
    await expect(this.page.locator("body")).toHaveCSS(
      "font-family",
      renderedFamily
    );
  }

  /** Assert the computed letter-spacing of a row title, which a typography preset styles. */
  async expectInterfaceLetterSpacing(spacing: string): Promise<void> {
    await expect(this.interfaceFontTitle).toHaveCSS("letter-spacing", spacing);
  }

  /** The rendered width of the Interface Font row title, once fonts load. */
  async interfaceFontTitleWidth(): Promise<number> {
    return this.interfaceFontTitle.evaluate(async (title) => {
      const style = getComputedStyle(title);
      await document.fonts.ready;
      // Load only the face under test. A fallback in the list, such as a
      // local() face for a font the machine lacks, would reject the load.
      const face = style.fontFamily.split(",")[0]!.trim();
      await document.fonts.load(
        `${style.fontWeight} ${style.fontSize} ${face}`,
        title.textContent ?? ""
      );
      const range = document.createRange();
      range.selectNodeContents(title);
      return range.getBoundingClientRect().width;
    });
  }

  /** Assert the server renders the interface font before any client script runs. */
  async expectServerRenderedInterfaceFont(font: InterfaceFont): Promise<void> {
    const response = await this.page.request.get(this.page.url());
    expect(response.ok()).toBe(true);
    expect(await response.text()).toContain(`data-interface-font="${font}"`);
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
