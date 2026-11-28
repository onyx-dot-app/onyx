import { test, expect } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { LONG_CHAT_TURNS, serveLongChat } from "@tests/e2e/utils/longChat";

test.describe("Chat render windowing", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
  });

  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("a long chat opens at its end, mounts the rows near the viewport, and scrolls both ways", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await sendMessage(page, "Start a chat to grow");
    const chatId = new URL(page.url()).searchParams.get("chatId");
    if (!chatId) throw new Error("The chat has no id");

    await serveLongChat(page, chatId);
    await chat.goto(chatId);

    // Opens at the end.
    await expect(chat.humanMessages.last()).toContainText(
      `Turn ${LONG_CHAT_TURNS}.`
    );
    await expect(chat.scrollToBottomButton).toBeHidden();

    // Every message has a row, but only those near the viewport are mounted.
    await expect(chat.messageRows).toHaveCount(LONG_CHAT_TURNS * 2);
    await expect
      .poll(() => chat.humanMessages.count())
      .toBeLessThan(LONG_CHAT_TURNS / 2);

    // The top of the chat mounts when scrolled to.
    await chat.scrollTo("top");
    await expect(chat.humanMessages.first()).toContainText("Turn 1.");

    // Scroll to bottom lands at the end.
    await chat.scrollToBottomButton.click();
    await expect(chat.scrollToBottomButton).toBeHidden();
    await expect(chat.humanMessages.last()).toContainText(
      `Turn ${LONG_CHAT_TURNS}.`
    );
  });
});
