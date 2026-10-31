import { expect, test } from "@playwright/test";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

test.use({ storageState: "admin_auth.json" });

/** Maps each settings slug to the header title shown on that page. */
const SLUG_TO_HEADER: Record<string, string> = {
  general: "Profile",
  "chat-preferences": "Chats",
  "accounts-access": "Accounts",
  connectors: "Connectors",
};

/**
 * Per-page selectors to hide before the screenshot, keyed by settings slug.
 *
 * These elements render values that change between CI runs, so leaving them
 * visible makes the visual diff fail for reasons unrelated to the change under
 * review.
 */
const SLUG_TO_HIDE_SELECTORS: Record<string, string[]> = {
  // The access-tokens list loads via SWR, so it flakily flips between
  // "Loading tokens..." and "No access tokens created." depending on whether
  // the fetch has settled.
  "accounts-access": ['[data-testid="access-token-list-status"]'],
  // Token counts come from the chats that earlier specs ran against a live
  // model, so the exact numbers differ on every run.
  usage: ['[data-testid="usage-model-tokens"]'],
};

for (const theme of THEMES) {
  test.describe(`Settings pages (${theme} mode)`, () => {
    test.beforeEach(async ({ page }) => {
      await setThemeBeforeNavigation(page, theme);
    });

    test("should screenshot each settings tab", async ({ page }) => {
      await page.goto("/app/settings/general");
      await page
        .getByTestId("settings-left-tab-navigation")
        .waitFor({ state: "visible" });

      const nav = page.getByTestId("settings-left-tab-navigation");
      const tabs = nav.locator("a");
      await expect(tabs.first()).toBeVisible({ timeout: 10_000 });
      const count = await tabs.count();

      for (let i = 0; i < count; i++) {
        const tab = tabs.nth(i);
        const href = await tab.getAttribute("href");
        const slug = href ? href.replace("/app/settings/", "") : `tab-${i}`;

        await tab.click();

        const expectedHeader = SLUG_TO_HEADER[slug];
        if (expectedHeader) {
          await expect(
            page
              .locator(".opal-content-md-header")
              .filter({ hasText: expectedHeader })
              .first()
          ).toBeVisible({ timeout: 10_000 });
        } else {
          await page.waitForLoadState("networkidle");
        }

        // Scope the screenshot to the settings container (rendered by
        // `SettingsLayouts.Root`) so dynamic app chrome (sidebar, greeting
        // text, etc.) doesn't cause spurious diffs.
        await expectElementScreenshot(
          page.locator("#page-wrapper-scroll-container"),
          {
            name: `settings-${theme}-${slug}`,
            hide: SLUG_TO_HIDE_SELECTORS[slug] ?? [],
          }
        );
      }
    });
  });
}
