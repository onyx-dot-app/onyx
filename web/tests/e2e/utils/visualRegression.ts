import type { Page, PageScreenshotOptions } from "@playwright/test";
import { expect } from "@playwright/test";

/**
 * Whether visual regression assertions are enabled.
 *
 * When `VISUAL_REGRESSION=true` is set, `expectScreenshot()` calls
 * `toHaveScreenshot()` which will fail if the screenshot differs from the
 * stored baseline.
 *
 * When disabled (the default), screenshots are still captured and saved but
 * mismatches do NOT fail the test — this lets CI collect screenshots for later
 * review without gating on them.
 */
const VISUAL_REGRESSION_ENABLED =
  process.env.VISUAL_REGRESSION?.toLowerCase() === "true";

/**
 * Default selectors to mask across all screenshots so that dynamic content
 * (timestamps, avatars, etc.) doesn't cause spurious diffs.
 */
const DEFAULT_MASK_SELECTORS: string[] = [
  // Add selectors for dynamic content that should be masked, e.g.:
  // '[data-testid="timestamp"]',
  // '[data-testid="user-avatar"]',
];

interface ScreenshotOptions {
  /**
   * Name for the screenshot file. If omitted, Playwright auto-generates one
   * from the test title.
   */
  name?: string;

  /**
   * Additional CSS selectors to mask (on top of the defaults).
   * Masked areas are replaced with a pink box so they don't cause diffs.
   */
  mask?: string[];

  /**
   * If true, capture the full scrollable page instead of just the viewport.
   * Defaults to false.
   */
  fullPage?: boolean;

  /**
   * Override the max diff pixel ratio for this specific screenshot.
   */
  maxDiffPixelRatio?: number;

  /**
   * Override the per-channel threshold for this specific screenshot.
   */
  threshold?: number;

  /**
   * Additional Playwright screenshot options.
   */
  screenshotOptions?: PageScreenshotOptions;
}

/**
 * Take a screenshot and optionally assert it matches the stored baseline.
 *
 * Behavior depends on the `VISUAL_REGRESSION` environment variable:
 * - `VISUAL_REGRESSION=true`  → assert via `toHaveScreenshot()` (fails on diff)
 * - Otherwise                 → capture and save the screenshot for review only
 *
 * Usage:
 * ```ts
 * import { expectScreenshot } from "@tests/e2e/utils/visualRegression";
 *
 * test("admin page looks right", async ({ page }) => {
 *   await page.goto("/admin/settings");
 *   await expectScreenshot(page, { name: "admin-settings" });
 * });
 * ```
 */
export async function expectScreenshot(
  page: Page,
  options: ScreenshotOptions = {}
): Promise<void> {
  const {
    name,
    mask = [],
    fullPage = false,
    maxDiffPixelRatio,
    threshold,
  } = options;

  // Combine default masks with per-call masks
  const allMaskSelectors = [...DEFAULT_MASK_SELECTORS, ...mask];
  const maskLocators = allMaskSelectors.map((selector) =>
    page.locator(selector)
  );

  // Build the screenshot name array (Playwright expects string[])
  const nameArg = name ? [name + ".png"] : undefined;

  if (VISUAL_REGRESSION_ENABLED) {
    // Assert mode — fail the test if the screenshot differs from baseline
    const screenshotOpts = {
      fullPage,
      mask: maskLocators.length > 0 ? maskLocators : undefined,
      ...(maxDiffPixelRatio !== undefined && { maxDiffPixelRatio }),
      ...(threshold !== undefined && { threshold }),
    };

    if (nameArg) {
      await expect(page).toHaveScreenshot(nameArg, screenshotOpts);
    } else {
      await expect(page).toHaveScreenshot(screenshotOpts);
    }
  } else {
    // Capture-only mode — save the screenshot without asserting
    const screenshotPath = name ? `output/screenshots/${name}.png` : undefined;
    await page.screenshot({
      path: screenshotPath,
      fullPage,
      mask: maskLocators.length > 0 ? maskLocators : undefined,
      ...options.screenshotOptions,
    });
  }
}
