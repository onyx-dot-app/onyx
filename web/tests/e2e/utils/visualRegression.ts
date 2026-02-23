import type { Locator, Page, PageScreenshotOptions } from "@playwright/test";
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

/**
 * Default selectors to hide (visibility: hidden) across all screenshots.
 * These elements are overlays or ephemeral UI that would cause spurious diffs.
 */
const DEFAULT_HIDE_SELECTORS: string[] = ['[data-testid="toast-container"]'];

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
   * CSS selectors for elements to hide (visibility: hidden) before taking
   * the screenshot. This removes elements from the visual output while
   * preserving their layout space, preventing size-related inconsistencies.
   */
  hide?: string[];

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

interface ElementScreenshotOptions {
  /**
   * Name for the screenshot file. If omitted, Playwright auto-generates one
   * from the test title.
   */
  name?: string;

  /**
   * Additional CSS selectors to mask (on top of the defaults).
   * The selectors are resolved relative to the page the locator belongs to.
   */
  mask?: string[];

  /**
   * CSS selectors for elements to hide (visibility: hidden) before taking
   * the screenshot. This removes elements from the visual output while
   * preserving their layout space, preventing size-related inconsistencies.
   */
  hide?: string[];

  /**
   * Override the max diff pixel ratio for this specific screenshot.
   */
  maxDiffPixelRatio?: number;

  /**
   * Override the per-channel threshold for this specific screenshot.
   */
  threshold?: number;
}

/**
 * Wait for all running CSS animations and transitions on the page to finish
 * before proceeding.  This prevents screenshot tests from being non-deterministic
 * when animated elements (e.g. slide-in cards) are still mid-flight.
 *
 * The implementation:
 *   1. Yields one animation frame so that any pending animations have a chance
 *      to register with the Web Animations API.
 *   2. Calls `Promise.allSettled` on every active animation's `.finished`
 *      promise so we wait for completion (or cancellation) of all of them.
 */
export async function waitForAnimations(page: Page): Promise<void> {
  await page.evaluate(async () => {
    // Allow any freshly-scheduled animations to start
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => resolve())
    );
    // Wait for every currently-registered animation to finish (or be cancelled)
    const animations = document
      .getAnimations()
      .filter(
        (animation) => animation.effect?.getTiming().iterations !== Infinity
      );
    await Promise.allSettled(animations.map((animation) => animation.finished));
  });
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
    hide = [],
    fullPage = false,
    maxDiffPixelRatio,
    threshold,
  } = options;

  // Wait for any in-flight CSS animations / transitions to settle so that
  // screenshots are deterministic (e.g. slide-in card animations on the
  // onboarding flow).
  await waitForAnimations(page);

  // Merge default hide selectors with per-call selectors
  const allHideSelectors = [...DEFAULT_HIDE_SELECTORS, ...hide];

  // Hide elements by setting visibility: hidden
  let styleHandle;
  if (allHideSelectors.length > 0) {
    styleHandle = await page.addStyleTag({
      content: allHideSelectors
        .map((selector) => `${selector} { visibility: hidden !important; }`)
        .join("\n"),
    });
  }

  try {
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
      const screenshotPath = name
        ? `output/screenshots/${name}.png`
        : undefined;
      await page.screenshot({
        path: screenshotPath,
        fullPage,
        mask: maskLocators.length > 0 ? maskLocators : undefined,
        ...options.screenshotOptions,
      });
    }
  } finally {
    // Remove the injected style tag to avoid affecting subsequent screenshots/assertions
    if (styleHandle) {
      await styleHandle.evaluate((el: HTMLStyleElement) => el.remove());
    }
  }
}

/**
 * Take a screenshot of a specific element and optionally assert it matches
 * the stored baseline.
 *
 * Works like {@link expectScreenshot} but scopes the screenshot to a single
 * `Locator` instead of the full page.
 *
 * Usage:
 * ```ts
 * import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";
 *
 * test("sidebar looks right", async ({ page }) => {
 *   await page.goto("/app");
 *   const sidebar = page.getByTestId("AppSidebar/new-session");
 *   await expectElementScreenshot(sidebar, { name: "sidebar-new-session" });
 * });
 * ```
 */
export async function expectElementScreenshot(
  locator: Locator,
  options: ElementScreenshotOptions = {}
): Promise<void> {
  const { name, mask = [], hide = [], maxDiffPixelRatio, threshold } = options;

  const page = locator.page();

  // Wait for any in-flight CSS animations / transitions to settle so that
  // element screenshots are deterministic (same reasoning as expectScreenshot).
  await waitForAnimations(page);

  // Merge default hide selectors with per-call selectors
  const allHideSelectors = [...DEFAULT_HIDE_SELECTORS, ...hide];

  // Hide elements by setting visibility: hidden
  let styleHandle;
  if (allHideSelectors.length > 0) {
    styleHandle = await page.addStyleTag({
      content: allHideSelectors
        .map((selector) => `${selector} { visibility: hidden !important; }`)
        .join("\n"),
    });
  }

  try {
    // Combine default masks with per-call masks
    const allMaskSelectors = [...DEFAULT_MASK_SELECTORS, ...mask];
    const maskLocators = allMaskSelectors.map((selector) =>
      page.locator(selector)
    );

    // Build the screenshot name array (Playwright expects string[])
    const nameArg = name ? [name + ".png"] : undefined;

    if (VISUAL_REGRESSION_ENABLED) {
      const screenshotOpts = {
        mask: maskLocators.length > 0 ? maskLocators : undefined,
        ...(maxDiffPixelRatio !== undefined && { maxDiffPixelRatio }),
        ...(threshold !== undefined && { threshold }),
      };

      if (nameArg) {
        await expect(locator).toHaveScreenshot(nameArg, screenshotOpts);
      } else {
        await expect(locator).toHaveScreenshot(screenshotOpts);
      }
    } else {
      // Capture-only mode — save the screenshot without asserting
      const screenshotPath = name
        ? `output/screenshots/${name}.png`
        : undefined;
      await locator.screenshot({
        path: screenshotPath,
        mask: maskLocators.length > 0 ? maskLocators : undefined,
      });
    }
  } finally {
    // Remove the injected style tag to avoid affecting subsequent screenshots/assertions
    if (styleHandle) {
      await styleHandle.evaluate((el: HTMLStyleElement) => el.remove());
    }
  }
}
