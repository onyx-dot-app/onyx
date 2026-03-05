/**
 * Playwright fixture that detects EE (Enterprise Edition) license state.
 *
 * Usage:
 * ```ts
 * import { test, expect } from "@tests/e2e/fixtures/eeFeatures";
 *
 * test("my EE-gated test", async ({ page, eeEnabled }) => {
 *   test.skip(!eeEnabled, "Requires active Enterprise license");
 *   // ... rest of test
 * });
 * ```
 *
 * The fixture:
 * - Authenticates as admin
 * - Fetches /api/settings to check ee_features_enabled
 * - Provides a boolean to the test BEFORE any navigation happens
 *
 * This lets tests call test.skip() synchronously at the top, which is the
 * correct Playwright pattern — never navigate then decide to skip.
 */

import { test as base, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

export const test = base.extend<{
  /** Whether EE features are enabled (valid enterprise license). */
  eeEnabled: boolean;
}>({
  eeEnabled: async ({ page }, use) => {
    // Try fetching settings directly first — avoids login if cookies are
    // already present (e.g. from a previous test in the same worker).
    let res = await page.request.get("/api/settings");
    if (!res.ok()) {
      // Not authenticated yet — login and retry.
      await loginAs(page, "admin");
      res = await page.request.get("/api/settings");
    }
    if (!res.ok()) {
      await use(false);
      return;
    }
    const settings = await res.json();
    await use(settings.ee_features_enabled === true);
  },
});

export { expect };
