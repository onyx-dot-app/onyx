/**
 * Playwright fixture that provides accessibility scanning helpers to any test.
 *
 * Usage:
 * ```ts
 * import { test, expect } from "@tests/e2e/fixtures/accessibility";
 *
 * test("page is accessible", async ({ page, expectAccessible }) => {
 *   await page.goto("/app");
 *   await page.waitForLoadState("networkidle");
 *   await expectAccessible();
 * });
 * ```
 *
 * Behavior:
 * - Violations of rules listed in STRICT_RULES → test fails (regressions blocked)
 * - All other violations → logged as test warnings (visible in reports, non-blocking)
 *
 * As rules are fixed across the app, add their IDs to STRICT_RULES in
 * `utils/accessibility.ts` to lock in the fix and prevent regressions.
 */

import { test as base, expect } from "@playwright/test";
import type { TestInfo } from "@playwright/test";
import type { AxeResults } from "axe-core";
import {
  scanAccessibility,
  partitionViolations,
  formatViolations,
  formatWarnings,
  type A11yScanOptions,
} from "@tests/e2e/utils/accessibility";

interface A11yFixtures {
  /** Scan the page; fail on strict rule violations, warn on the rest. */
  expectAccessible: (options?: A11yScanOptions) => Promise<void>;
  /** Run an axe scan and return raw results for custom handling. */
  a11yScan: (options?: A11yScanOptions) => Promise<AxeResults>;
}

export const test = base.extend<A11yFixtures>({
  expectAccessible: async ({ page }, use, testInfo: TestInfo) => {
    await use(async (options?: A11yScanOptions) => {
      const results = await scanAccessibility(page, options);
      const { strict, warnings } = partitionViolations(results.violations);

      if (warnings.length > 0) {
        testInfo.annotations.push({
          type: "a11y-warnings",
          description: `${
            warnings.length
          } non-strict a11y violation(s):\n${formatWarnings(warnings)}`,
        });
      }

      expect(
        strict,
        strict.length > 0
          ? `Strict a11y rule regression:\n${formatViolations(strict)}`
          : ""
      ).toHaveLength(0);
    });
  },

  a11yScan: async ({ page }, use) => {
    await use(async (options?: A11yScanOptions) => {
      return scanAccessibility(page, options);
    });
  },
});

export { expect };
