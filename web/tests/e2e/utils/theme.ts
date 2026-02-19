import type { Page } from "@playwright/test";

export const THEMES = ["light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

/**
 * Injects the given theme into localStorage via `addInitScript` so that
 * `next-themes` applies it on first render. Call this in `beforeEach`
 * **before** any `page.goto()`.
 */
export async function setThemeBeforeNavigation(
  page: Page,
  theme: Theme
): Promise<void> {
  await page.addInitScript((t: string) => {
    localStorage.setItem("theme", t);
  }, theme);
}
