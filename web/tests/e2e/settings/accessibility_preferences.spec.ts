import { expect, test } from "@playwright/test";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import { LONG_CHAT_TURNS, serveLongChat } from "@tests/e2e/utils/longChat";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { SettingsAppearancePage } from "@tests/e2e/pages/SettingsAppearancePage";

// Past the 4 s auto-dismiss and the toast's leave animation.
const PAST_AUTO_DISMISS_MS = 10_000;

// Each test uses a fresh random user: these preferences apply to every page
// the user opens, so changing them on a shared user would leak into other specs.
test.describe("Accessibility preferences", () => {
  test("Reduced motion applies at once and renders from the server", async ({
    page,
  }) => {
    await loginAsRandomUser(page);
    const settingsPage = new SettingsAppearancePage(page);
    await settingsPage.goto();

    await settingsPage.chooseAppearanceOption(
      settingsPage.motionSelect,
      "Reduced"
    );
    await settingsPage.expectAppearance("data-motion", "reduced");
    // Toasts animate in by default; reduced motion turns that off.
    await settingsPage.raiseUpdateFailedToasts(1);
    await settingsPage.expectToastAnimationName("none");

    // The save refreshed the appearance cookie, so the server layout renders
    // reduced motion on first paint.
    await settingsPage.expectServerRenderedAppearance("data-motion", "reduced");
  });

  test("Stay on screen keeps toasts until the user closes them", async ({
    page,
  }) => {
    await page.clock.install();
    await loginAsRandomUser(page);
    const settingsPage = new SettingsAppearancePage(page);
    await settingsPage.goto();

    await settingsPage.chooseAppearanceOption(
      settingsPage.popupsSelect,
      "Stay on screen"
    );
    // One more than the stack shows, so the oldest piles below it.
    await settingsPage.raiseUpdateFailedToasts(4);
    await page.clock.fastForward(PAST_AUTO_DISMISS_MS);
    await expect(settingsPage.updateFailedToasts).toHaveCount(4);
    await expect(settingsPage.updateFailedToasts.first()).toBeVisible();

    await settingsPage.closeAllToasts();
  });

  test("Dynamic conversations off keeps every message of a long chat mounted", async ({
    page,
  }) => {
    await loginAsRandomUser(page);
    const settingsPage = new SettingsAppearancePage(page);
    await settingsPage.goto();
    await settingsPage.setDynamicConversations(false);

    const chat = new ChatPage(page);
    await chat.goto();
    await sendMessage(page, "Start a chat to grow");
    const chatId = new URL(page.url()).searchParams.get("chatId");
    if (!chatId) throw new Error("The chat has no id");

    await serveLongChat(page, chatId);
    await chat.goto(chatId);
    await expect(chat.humanMessages.last()).toContainText(
      `Turn ${LONG_CHAT_TURNS}.`
    );
    // With unloading on, only the rows near the viewport mount.
    await expect(chat.humanMessages).toHaveCount(LONG_CHAT_TURNS);
    await expect(chat.humanMessages.first()).toContainText("Turn 1.");
  });
});
