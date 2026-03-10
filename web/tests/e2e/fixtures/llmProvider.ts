/**
 * Playwright fixture that ensures a public LLM provider is available.
 *
 * Usage:
 * ```ts
 * // Import from this file instead of @playwright/test
 * import { test, expect } from "@tests/e2e/fixtures/llmProvider";
 *
 * test("my test that needs an LLM provider", async ({ page, llmProviderId }) => {
 *   // llmProviderId is the ID of the provider that was created (or null if
 *   // one already existed). The fixture handles cleanup automatically.
 * });
 * ```
 *
 * The fixture:
 * - Authenticates as admin
 * - Creates a public LLM provider if none exists
 * - Provides the created provider ID to the test
 * - Cleans up the provider after all tests in the file complete
 */

import { test as base, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

export const test = base.extend<{
  /**
   * The ID of the public LLM provider created by this fixture, or `null`
   * if a public provider already existed.
   */
  llmProviderId: number | null;
}>({
  llmProviderId: async ({ page }, use) => {
    // Authenticate as admin to be able to create/list providers
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const client = new OnyxApiClient(page.request);
    const createdId = await client.ensurePublicProvider();
    await use(createdId);

    // Cleanup: only delete if we created one
    if (createdId !== null) {
      // Re-authenticate in case the test changed the session
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await client.deleteProvider(createdId);
    }
  },
});

export { expect };
