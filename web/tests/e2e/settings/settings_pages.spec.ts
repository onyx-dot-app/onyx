import { expect, test } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { AppSidebarPage } from "@tests/e2e/pages/AppSidebarPage";
import { SettingsThirdPartyAccessPage } from "@tests/e2e/pages/SettingsThirdPartyAccessPage";
import { SettingsAccountPage } from "@tests/e2e/pages/SettingsAccountPage";
import { SettingsChatPreferencesPage } from "@tests/e2e/pages/SettingsChatPreferencesPage";
import { SettingsAppearancePage } from "@tests/e2e/pages/SettingsAppearancePage";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import { mockLlmNonce } from "@tests/e2e/utils/mockLlm";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

test.use({ storageState: "admin_auth.json" });

/** Maps each settings slug to the header title shown on that page. */
const SLUG_TO_HEADER: Record<string, string> = {
  account: "Profile",
  appearance: "General",
  "chat-preferences": "Model Preferences",
  "third-party-access": "Access Tokens",
  usage: "Usage This Period",
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
  "third-party-access": ['[data-testid="access-token-list-status"]'],
  // Token counts come from the chats that earlier specs ran against a live
  // model, so the exact numbers differ on every run. The date range ends today.
  usage: [
    '[data-testid="usage-model-tokens"]',
    '[role="group"][aria-label="Date range"]',
  ],
};

for (const theme of THEMES) {
  test.describe(`Settings pages (${theme} mode)`, () => {
    test.beforeEach(async ({ page }) => {
      await setThemeBeforeNavigation(page, theme);
    });

    test("should screenshot each settings tab", async ({ page }) => {
      await page.goto("/app/settings/account");
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
            // Exact text, so a header does not match a longer title still on
            // screen from the previous tab.
            page
              .locator(".opal-content-title-row")
              .getByText(expectedHeader, { exact: true })
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

// Released CLI binaries open these paths.
test("old settings paths open their tabs", async ({ page }) => {
  await new SettingsAccountPage(page).load("/app/settings/general");
  await new SettingsThirdPartyAccessPage(page).load(
    "/app/settings/accounts-access"
  );
});

// The width is stored per browser, so the fresh context of this test starts
// with the reading-width default. The window is wider than the wide cap.
test.describe("Transcript Width", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test("Wide widens a conversation to the wide cap, not the landing page", async ({
    page,
  }) => {
    const appearancePage = new SettingsAppearancePage(page);
    const chatPage = new ChatPage(page);
    const sidebar = new AppSidebarPage(page);

    await chatPage.goto();
    await sendMessage(page, `Hello ${mockLlmNonce()}`);
    const sessionId = chatPage.currentSessionId();
    await chatPage.expectChatColumnWidth("reading");

    await appearancePage.goto();
    await appearancePage.setTranscriptWidth("Wide");
    // A page load starts at reading width, so a wide column shows that the
    // stored value was read.
    await chatPage.goto(sessionId);
    await chatPage.expectChatColumnWidth("wide");

    // The landing page keeps the reading width while Wide is on.
    await sidebar.newSession();
    await chatPage.expectChatColumnWidth("reading");

    await appearancePage.goto();
    await expect(appearancePage.transcriptWidthSelect).toHaveValue("Wide");
  });
});

// Uses a fresh user: the theme is saved on the user row, and changing it on
// the shared admin would leak dark mode into concurrently running specs.
test("theme buttons switch to dark mode and the choice persists", async ({
  page,
}) => {
  await loginAsRandomUser(page);
  const appearancePage = new SettingsAppearancePage(page);

  await appearancePage.goto();
  await appearancePage.chooseTheme("Dark");
  await appearancePage.expectDarkMode(true);

  await appearancePage.reload();
  await expect(appearancePage.themeButton("Dark")).toHaveAttribute(
    "aria-pressed",
    "true"
  );
  await appearancePage.expectDarkMode(true);

  await appearancePage.chooseTheme("Light");
  await appearancePage.expectDarkMode(false);
});

// Uses a fresh user: these preferences are saved on the user row.
test("overlapping preference saves keep each other, and a failed one shows the saved state", async ({
  page,
}) => {
  await loginAsRandomUser(page);
  const preferences = new SettingsChatPreferencesPage(page);
  await preferences.goto();
  await preferences.expectCollapseLargePastes(true);

  // The first save stays in flight while the second completes.
  const pastes = await preferences.holdNextCollapseLargePastesSave();
  await preferences.toggleCollapseLargePastes();
  await pastes.forwarded;
  await preferences.setSendBehavior("Interrupt current work");
  pastes.release();
  await pastes.delivered;
  await preferences.expectCollapseLargePastes(false);
  await expect(preferences.sendBehavior).toHaveValue("Interrupt current work");

  // A failed save shows what the server holds and keeps the other change.
  await preferences.failNextSendBehaviorSave();
  await preferences.chooseSendBehavior("After the current step");
  await expect(preferences.sendBehavior).toHaveValue("Interrupt current work");
  await preferences.expectCollapseLargePastes(false);

  await preferences.goto();
  await preferences.expectCollapseLargePastes(false);
  await expect(preferences.sendBehavior).toHaveValue("Interrupt current work");
});
